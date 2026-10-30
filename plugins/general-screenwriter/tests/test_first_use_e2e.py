import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
FEISHU_SCRIPTS = ROOT / "skills" / "feishu-knowledge-store" / "scripts"
SETUP_SCRIPTS = ROOT / "skills" / "setup" / "scripts"
for location in (FEISHU_SCRIPTS, SETUP_SCRIPTS):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

import lark_cli_context
import setup_cli
import store_cli
from lark_auth import REQUIRED_SCOPES
from lark_cli import LarkCli


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeSession:
    def __init__(self, profiles=None, version="1.0.95"):
        self.version = version
        self.profiles = [dict(item) for item in (profiles or [])]
        self.authenticated = False
        self.open_id = "ou_owner"
        self.target_edit = True
        self.nodes = {"target-node": [], "source-root": []}
        self.docs = {}
        self.created_titles = []
        self.create_attempts = {}
        self.verification_create_attempts = 0
        self.verification_fetch_attempts = 0
        self.verification_tokens = set()
        self.fail_verification_create_once = False
        self.fail_next_verification_fetch = 0
        self.fail_next_list_nodes = 0
        self.fail_always_list_nodes = False
        self.list_node_attempts = 0
        self.target_root_list_attempts = 0
        self.device_attempts = 0
        self.expired_codes = set()
        self.last_binary = None
        self.private_binary = None
        self._next = 0

    def add_profile(self, name, app_id="cli_offline"):
        if not any(item.get("name") == name for item in self.profiles):
            self.profiles.append({"name": name, "appId": app_id})

    def _new_document(self, parent, title, content):
        self._next += 1
        doc_token = f"doc-{self._next}"
        node_token = f"node-{self._next}"
        document = {"revision_id": 3, "content": content}
        self.docs[doc_token] = dict(document)
        self.docs[node_token] = dict(document)
        self.nodes.setdefault(parent, []).append({
            "title": title,
            "node_token": node_token,
            "obj_token": node_token,
        })
        self.created_titles.append(title)
        self.create_attempts[title] = self.create_attempts.get(title, 0) + 1
        return doc_token, node_token

    def node_payload(self, token):
        if token == "source-node":
            return {"data": {"node": {
                "space_id": "source-space",
                "node_token": "source-node",
                "obj_token": "source-doc",
            }}}
        if token == "target-node":
            return {"data": {"node": {
                "space_id": "target-space",
                "node_token": "target-node",
                "obj_token": "target-doc",
            }}}
        return {"data": {"node": {
            "space_id": "target-space",
            "node_token": token,
            "obj_token": token,
        }}}

    def fetch_document(self, token):
        if token == "source-doc":
            return {"revision_id": 1, "content": "# source"}
        document = self.docs.get(token)
        if document is None:
            raise RuntimeError(f"unknown document: {token}")
        return dict(document)


class FakeRunner:
    def __init__(self, session, environ, global_cli=None):
        self.session = session
        self.environ = environ
        self.calls = []
        self.allowed_binaries = set()
        if global_cli is not None:
            self.allowed_binaries.add(Path(global_cli).resolve())

    def _npm(self, command):
        prefix = Path(command[command.index("--prefix") + 1])
        binary_name = "lark-cli.cmd" if os.name == "nt" else "lark-cli"
        binary = prefix / "node_modules" / ".bin" / binary_name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"offline fake cli\n")
        self.session.private_binary = binary
        self.allowed_binaries.add(binary.resolve())
        return Completed()

    @staticmethod
    def _args(command):
        arguments = list(command[1:])
        if arguments[:2] == ["--profile", arguments[1] if len(arguments) > 1 else ""]:
            arguments = arguments[2:]
        return arguments

    def _profile_list(self):
        return Completed(json.dumps(self.session.profiles))

    def _node_list(self, arguments):
        self.session.list_node_attempts += 1
        if self.session.fail_always_list_nodes:
            raise TimeoutError("offline node-list timeout")
        if self.session.fail_next_list_nodes:
            self.session.fail_next_list_nodes -= 1
            raise TimeoutError("offline node-list timeout")
        parent = None
        if "--parent-node-token" in arguments:
            parent = arguments[arguments.index("--parent-node-token") + 1]
        if parent == "target-node":
            self.session.target_root_list_attempts += 1
        return Completed(json.dumps({"data": {
            "items": list(self.session.nodes.get(parent, [])),
        }}))

    def _verification_create(self, title, parent, content):
        self.session.verification_create_attempts += 1
        result = self._create_document(title, parent, content)
        if self.session.fail_verification_create_once:
            self.session.fail_verification_create_once = False
            self.session.fail_next_verification_fetch += 1
            raise TimeoutError("offline verification write timeout after write")
        return result

    def _create_document(self, title, parent, content):
        doc_token, node_token = self.session._new_document(parent, title, content)
        if title == "AI_KB_WRITE_VERIFICATION_V1":
            self.session.verification_tokens.update((doc_token, node_token))
        return Completed(json.dumps({"code": 0, "data": {"document": {
            "document_id": doc_token,
            "revision_id": 3,
            "node_token": node_token,
        }}}))

    def __call__(self, command, **_kwargs):
        self.calls.append(list(command))
        if command[0] == "npm":
            return self._npm(command)

        binary = Path(command[0])
        if binary.resolve() not in self.allowed_binaries:
            raise FileNotFoundError(str(binary))
        self.session.last_binary = binary
        arguments = self._args(command)

        if arguments == ["--version"]:
            return Completed(f"lark-cli version {self.session.version}\n")
        if arguments in (
            ["help"],
            ["schema"],
            ["auth", "login", "--help"],
            ["wiki", "--help"],
            ["docs", "--help"],
            ["drive", "--help"],
        ):
            return Completed()

        if arguments == ["profile", "list"]:
            return self._profile_list()

        if arguments[:2] == ["auth", "qrcode"]:
            output = arguments[arguments.index("--output") + 1]
            Path(output).write_bytes(b"\x89PNG\r\n\x1a\n")
            return Completed('{"ok":true}')

        if arguments[:2] == ["auth", "login"] and "--no-wait" in arguments:
            self.session.device_attempts += 1
            code = f"device-{self.session.device_attempts}"
            scopes = arguments[arguments.index("--scope") + 1]
            return Completed(json.dumps({
                "verification_url": f"https://example.test/device/{code}",
                "device_code": code,
                "expires_in": 600,
                "scopes": scopes.split(),
            }))

        if arguments[:2] == ["auth", "login"] and "--device-code" in arguments:
            code = arguments[arguments.index("--device-code") + 1]
            if code in self.session.expired_codes:
                return Completed(
                    '{"ok":false,"error":{"subtype":"token_expired"}}',
                    returncode=1,
                )
            self.session.authenticated = True
            return Completed(json.dumps({
                "event": "authorization_complete",
                "user_open_id": self.session.open_id,
            }))

        if arguments[:2] == ["auth", "status"]:
            return Completed(json.dumps({"data": {"user": {
                "open_id": self.session.open_id,
            }}}))

        if arguments[:2] == ["wiki", "+node-get"]:
            token = arguments[arguments.index("--node-token") + 1]
            return Completed(json.dumps(self.session.node_payload(token)))

        if arguments[:2] == ["wiki", "+node-list"]:
            return self._node_list(arguments)

        if arguments[:2] == ["docs", "+fetch"]:
            token = arguments[arguments.index("--doc") + 1]
            if token in self.session.verification_tokens:
                self.session.verification_fetch_attempts += 1
                if self.session.fail_next_verification_fetch:
                    self.session.fail_next_verification_fetch -= 1
                    raise TimeoutError("offline verification readback timeout")
            return Completed(json.dumps({"data": {
                "document": self.session.fetch_document(token),
            }}))

        if arguments[:2] == ["docs", "+create"]:
            title = arguments[arguments.index("--title") + 1]
            parent = arguments[arguments.index("--parent-token") + 1]
            content_ref = arguments[arguments.index("--content") + 1]
            content = Path(content_ref[1:]).read_text(encoding="utf-8")
            if title == "AI_KB_WRITE_VERIFICATION_V1":
                return self._verification_create(title, parent, content)
            return self._create_document(title, parent, content)

        if arguments[:2] == ["docs", "+update"]:
            token = arguments[arguments.index("--doc") + 1]
            revision = int(arguments[arguments.index("--revision-id") + 1])
            content_ref = arguments[arguments.index("--content") + 1]
            content = Path(content_ref[1:]).read_text(encoding="utf-8")
            document = self.session.docs.get(token)
            if document is None:
                raise RuntimeError(f"unknown document: {token}")
            if document["revision_id"] != revision:
                return Completed(
                    '{"code":1,"error":"revision conflict"}',
                    returncode=1,
                )
            document["revision_id"] = revision + 2
            document["content"] = content
            return Completed(json.dumps({"code": 0, "data": {"document": {
                "revision_id": document["revision_id"],
            }}}))

        if arguments[:3] == ["drive", "permission.members", "auth"]:
            return Completed(json.dumps({"data": {
                "auth_result": self.session.target_edit,
            }}))

        raise AssertionError(f"unexpected offline CLI command: {arguments}")


class FakePopen:
    def __init__(self, session):
        self.session = session
        self.calls = []
        self.returncode = 0

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if "--name" in command:
            self.session.add_profile(command[command.index("--name") + 1])
        stream = kwargs.get("stdout")
        if stream is not None:
            stream.write(json.dumps({
                "verification_url": "https://example.test/app-config",
                "console_url": "https://example.test/console",
            }))
            stream.flush()
        return self

    def poll(self):
        return self.returncode


class FirstUseHarness:
    def __init__(
        self,
        *,
        profiles=None,
        global_cli=None,
        original_request="offline first-use request",
    ):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.user_data = self.root / "user-data"
        self.user_data.mkdir()
        self.original_request = original_request
        self.state_path = self.root / "setup-resume-context.json"
        self.resume_context = {
            "schema_version": 1,
            "original_request": original_request,
            "profile": "team-a",
            "stage": "start",
            "ready": False,
        }
        self.state_path.write_text(json.dumps(self.resume_context), encoding="utf-8")
        self.environ = {
            "GENERAL_SCREENWRITER_USER_DATA": str(self.user_data),
            "APPDATA": "",
            "LOCALAPPDATA": "",
            "PATH": "",
        }
        self.global_cli = Path(global_cli) if global_cli else None
        if self.global_cli is not None:
            self.environ["LARK_CLI_PATH"] = str(self.global_cli)
        self.session = FakeSession(profiles=profiles)
        self.runner = FakeRunner(self.session, self.environ, self.global_cli)
        self.popen = FakePopen(self.session)
        self.config_path = self.root / "feishu-knowledge-base.json"
        self._patches = [
            mock.patch.dict(os.environ, {"PATH": ""}, clear=False),
            mock.patch("lark_runtime.shutil.which", return_value="npm"),
        ]
        for patch in self._patches:
            patch.start()

    def _cleanup(self):
        for patch in reversed(self._patches):
            patch.stop()
        self.temp.cleanup()

    @property
    def which(self):
        if self.global_cli is None:
            return lambda _name: None
        return lambda name: str(self.global_cli) if name == "lark-cli" else None

    def _run_command(self, arguments):
        context_text = self.state_path.read_text(encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            setup_cli.main(
                [*arguments, "--resume-context", context_text],
                environ=self.environ,
                runner=self.runner,
                popen=self.popen,
                which=self.which,
            )
        payload = json.loads(output.getvalue())
        if "resume_context" not in payload:
            raise AssertionError(
                f"setup command dropped resume context: {payload}"
            )
        self.state_path.write_text(
            json.dumps(payload["resume_context"]),
            encoding="utf-8",
        )
        self.resume_context = json.loads(
            self.state_path.read_text(encoding="utf-8")
        )
        return payload

    def auth_start(self, profile="team-a"):
        return self._run_command([
            "auth-start",
            "--profile", profile,
            "--mode", "per_user",
            "--json",
        ])

    def auth_complete(self, device_code, profile="team-a"):
        return self._run_command([
            "auth-complete",
            "--profile", profile,
            "--device-code", device_code,
            "--json",
        ])

    def config_from_links(self, profile="team-a"):
        return self._run_command([
            "config-from-links",
            "--profile", profile,
            "--config", str(self.config_path),
            "--source-url", "https://team.feishu.cn/wiki/source-node",
            "--target-url", "https://team.feishu.cn/wiki/target-node",
            "--json",
        ])

    def doctor(self, profile="team-a"):
        return self._run_command([
            "doctor",
            "--profile", profile,
            "--config", str(self.config_path),
            "--json",
        ])

    def target_init(self, *, initializer, authorized, profile="team-a"):
        arguments = [
            "target-init",
            "--profile", profile,
            "--config", str(self.config_path),
            "--json",
        ]
        if initializer:
            arguments.append("--initializer")
        if authorized:
            arguments.append("--authorized")
        return self._run_command(arguments)

    def write_verify(self, *, authorized, profile="team-a"):
        arguments = [
            "write-verify",
            "--profile", profile,
            "--config", str(self.config_path),
            "--json",
        ]
        if authorized:
            arguments.append("--authorized")
        return self._run_command(arguments)

    def resume(self):
        return setup_cli.restore_original_request(self.resume_context)

    def authorize(self):
        first = self.auth_start()
        assert first["status"] == "waiting_user", first
        if first["stage"] == "app_config":
            second = self.auth_start()
        else:
            assert first["stage"] == "device_auth", first
            second = first
        assert second["status"] == "waiting_user", second
        assert second["stage"] == "device_auth", second
        self.session.expired_codes.add(second["device_code"])
        expired = self.auth_complete(second["device_code"])
        assert expired["status"] == "device_code_expired", expired
        assert tuple(expired["scopes"]) == tuple(REQUIRED_SCOPES), expired
        third = self.auth_start()
        assert third["status"] == "waiting_user", third
        assert third["stage"] == "device_auth", third
        completed = self.auth_complete(third["device_code"])
        assert completed["status"] == "authorized", completed
        return second, third

    def configure_and_initialize(self):
        self.authorize()
        configured = self.config_from_links()
        assert configured["status"] == "configured", configured
        self.session.target_edit = True
        initialized = self.target_init(initializer=True, authorized=True)
        assert initialized["status"] == "write_verification_required", initialized
        return initialized


class FirstUseEndToEndTests(unittest.TestCase):
    def test_private_install_full_first_use_reaches_ready(self):
        original_request = "sync the source wiki into the target wiki"
        harness = FirstUseHarness(original_request=original_request)
        self.addCleanup(harness._cleanup)

        first = harness.auth_start()
        self.assertEqual(first["status"], "waiting_user")
        self.assertEqual(first["stage"], "app_config")
        npm_calls = [call for call in harness.runner.calls if call[0] == "npm"]
        self.assertEqual(len(npm_calls), 1)
        self.assertNotIn("-g", npm_calls[0])
        self.assertNotIn("skills", npm_calls[0])
        self.assertIn(
            str(harness.user_data.resolve()),
            npm_calls[0][npm_calls[0].index("--prefix") + 1],
        )
        self.assertTrue(harness.session.private_binary.is_file())

        second, third = harness.authorize()
        self.assertIsNot(first, second)
        self.assertIsNot(second, third)
        scopes = [
            call[call.index("--scope") + 1]
            for call in harness.runner.calls
            if call[0] != "npm" and "auth" in call and "login" in call and "--scope" in call
        ]
        self.assertGreaterEqual(len(scopes), 2)
        self.assertEqual(scopes[0], scopes[1])

        configured = harness.config_from_links()
        self.assertEqual(configured["status"], "configured")
        self.assertTrue(harness.config_path.is_file())

        harness.session.target_edit = False
        blocked = harness.doctor()
        self.assertEqual(blocked["status"], "resource_grant_required")
        self.assertIn("resource_access", blocked["blocking_checks"])
        harness.session.target_edit = True

        waiting = harness.target_init(initializer=False, authorized=True)
        self.assertEqual(waiting["status"], "waiting_initializer")
        self.assertEqual(harness.session.created_titles, [])

        initialized = harness.target_init(initializer=True, authorized=True)
        self.assertEqual(initialized["status"], "write_verification_required")
        self.assertGreater(len(harness.session.created_titles), 0)

        verified = harness.write_verify(authorized=True)
        self.assertTrue(verified["ready"])
        final = harness.doctor()
        self.assertTrue(final["ready"])
        self.assertEqual(harness.resume(), original_request)

    def test_existing_global_cli_is_reused_without_installing(self):
        global_cli = Path(tempfile.gettempdir()) / "offline-global-lark-cli.cmd"
        harness = FirstUseHarness(
            profiles=[{"name": "team-a", "appId": "cli_existing"}],
            global_cli=global_cli,
        )
        self.addCleanup(harness._cleanup)

        result = harness.auth_start()

        self.assertEqual(result["status"], "waiting_user")
        self.assertEqual(result["stage"], "device_auth")
        self.assertFalse(any(call[0] == "npm" for call in harness.runner.calls))
        # The session records the binary as the resolver returned it, which is
        # the resolved absolute path; compare against the same resolved form.
        self.assertEqual(harness.session.last_binary, global_cli.resolve())

    def test_new_profile_preserves_existing_profiles(self):
        global_cli = Path(tempfile.gettempdir()) / "offline-global-lark-cli.cmd"
        harness = FirstUseHarness(
            profiles=[{"name": "other", "appId": "cli_other"}],
            global_cli=global_cli,
        )
        self.addCleanup(harness._cleanup)
        before = copy.deepcopy(harness.session.profiles)

        first = harness.auth_start()
        self.assertEqual(first["status"], "waiting_user")
        self.assertEqual(first["stage"], "app_config")
        self.assertEqual(harness.session.profiles[0], before[0])
        self.assertTrue(any(item["name"] == "team-a" for item in harness.session.profiles))
        self.assertFalse(any("config" in call and "rename" in call for call in harness.runner.calls))

    def test_device_code_expiry_restarts_with_same_scope_set(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        first = harness.auth_start()
        self.assertEqual(first["stage"], "app_config")
        device = harness.auth_start()
        self.assertEqual(device["stage"], "device_auth")
        first_scope = next(
            call[call.index("--scope") + 1]
            for call in reversed(harness.runner.calls)
            if "auth" in call and "login" in call and "--scope" in call
        )
        harness.session.expired_codes.add(device["device_code"])

        expired = harness.auth_complete(device["device_code"])
        retry = harness.auth_start()
        retry_scope = next(
            call[call.index("--scope") + 1]
            for call in reversed(harness.runner.calls)
            if "auth" in call and "login" in call and "--scope" in call
        )

        self.assertEqual(expired["status"], "device_code_expired")
        self.assertEqual(expired["scopes"], list(REQUIRED_SCOPES))
        self.assertEqual(retry["stage"], "device_auth")
        self.assertEqual(retry_scope, first_scope)

    def test_ambiguous_target_stops_before_writes(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        harness.authorize()
        self.assertEqual(harness.config_from_links()["status"], "configured")
        harness.session.nodes["target-node"] = [
            {"title": "00_使用说明", "node_token": "dup-a"},
            {"title": "00_使用说明", "node_token": "dup-b"},
        ]
        before_attempts = harness.session.target_root_list_attempts

        report = harness.target_init(initializer=True, authorized=True)

        self.assertEqual(report["status"], "control_tree_ambiguous")
        self.assertEqual(harness.session.created_titles, [])
        self.assertTrue(report["preview"]["control_tree"]["duplicates"])
        self.assertEqual(harness.session.target_root_list_attempts - before_attempts, 1)
        doctor = harness.doctor()
        self.assertEqual(doctor["status"], "control_tree_ambiguous")
        self.assertEqual(harness.session.created_titles, [])

    def test_write_result_uncertain_reads_back_without_blind_retry(self):
        original_request = "ingest the already-selected source and target"
        harness = FirstUseHarness(original_request=original_request)
        self.addCleanup(harness._cleanup)
        harness.configure_and_initialize()

        harness.session.fail_verification_create_once = True
        fetch_attempts_before = harness.session.verification_fetch_attempts
        uncertain = harness.write_verify(authorized=True)

        self.assertEqual(uncertain["status"], "write_result_uncertain")
        self.assertEqual(harness.session.verification_create_attempts, 1)
        self.assertGreater(
            harness.session.verification_fetch_attempts,
            fetch_attempts_before,
        )
        self.assertTrue(any(
            "docs" in call and "+fetch" in call
            for call in harness.runner.calls
        ))

        readback = harness.doctor()
        self.assertTrue(readback["ready"])
        self.assertEqual(harness.session.verification_create_attempts, 1)
        self.assertEqual(harness.resume(), original_request)

    def test_transient_tree_read_retries_but_never_loops(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        harness.configure_and_initialize()
        self.assertTrue(harness.write_verify(authorized=True)["ready"])
        harness.session.fail_next_list_nodes = 1
        before = harness.session.list_node_attempts

        recovered = harness.doctor()

        self.assertTrue(recovered["ready"])
        self.assertGreaterEqual(harness.session.list_node_attempts - before, 2)

        harness.session.fail_always_list_nodes = True
        before = harness.session.list_node_attempts
        blocked = harness.doctor()
        self.assertEqual(blocked["status"], "network_blocked")
        self.assertLessEqual(harness.session.list_node_attempts - before, 2)

    def test_target_init_retries_transient_read_failure(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        harness.authorize()
        self.assertEqual(harness.config_from_links()["status"], "configured")
        harness.session.fail_next_list_nodes = 1
        before = harness.session.list_node_attempts

        report = harness.target_init(initializer=True, authorized=True)

        self.assertEqual(report["status"], "write_verification_required")
        self.assertGreaterEqual(harness.session.list_node_attempts - before, 2)

    def test_write_verify_retries_transient_read_failure(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        harness.configure_and_initialize()
        harness.session.fail_next_list_nodes = 1
        before = harness.session.list_node_attempts

        report = harness.write_verify(authorized=True)

        self.assertTrue(report["ready"])
        self.assertGreaterEqual(harness.session.list_node_attempts - before, 2)

    def test_persistent_network_failure_is_bounded(self):
        harness = FirstUseHarness()
        self.addCleanup(harness._cleanup)
        harness.authorize()
        self.assertEqual(harness.config_from_links()["status"], "configured")
        harness.session.fail_always_list_nodes = True
        before = harness.session.list_node_attempts

        report = harness.target_init(initializer=True, authorized=True)

        self.assertEqual(report["status"], "network_blocked")
        self.assertLessEqual(harness.session.list_node_attempts - before, 2)

    def test_operational_sync_path_keeps_the_setup_profile(self):
        harness = FirstUseHarness(original_request="sync the source wiki into the target wiki")
        self.addCleanup(harness._cleanup)
        harness.authorize()
        self.assertEqual(harness.config_from_links()["status"], "configured")
        self.assertEqual(
            harness.target_init(initializer=True, authorized=True)["status"],
            "write_verification_required",
        )
        self.assertTrue(harness.write_verify(authorized=True)["ready"])
        harness.session.nodes[None] = [{
            "title": "src", "node_token": "src", "obj_token": "src-doc",
            "obj_type": "docx",
        }]

        profiles_seen = []

        def bound_resolve(**kwargs):
            # Keep the real search order and profile resolution; only the
            # process boundary is the harness' offline runner.
            kwargs.setdefault("runner", harness.runner)
            kwargs.setdefault("which", harness.which)
            return lark_cli_context.resolve_cli_context(**kwargs)

        def bound_cli(binary, identity="user", runner=None, profile=None):
            profiles_seen.append(profile)
            return LarkCli(binary, identity=identity, runner=harness.runner, profile=profile)

        run_dir = harness.root / "run-1"
        staging = run_dir / "wiki_staging"
        staging.mkdir(parents=True)
        (staging / "page.md").write_text(
            "---\n"
            "title: 世界观\n"
            "series_id: s\n"
            "project_id: p\n"
            "page_type: worldview\n"
            "source_node_tokens:\n"
            "  - src\n"
            "source_revision_parts:\n"
            "  - \"1\"\n"
            "source_edit_time_parts:\n"
            "  - 1756572300000\n"
            "---\n"
            "AI content\n",
            encoding="utf-8",
        )
        (staging / "_manifest.json").write_text(json.dumps({
            "version": 9, "series": {}, "root": [],
            "entries": [{
                "path": "page.md", "key": "s/p/worldview",
                "source_revisions": {"src": "1"}, "page_type": "worldview",
                "series_id": "s", "project_id": "p",
            }],
        }, ensure_ascii=False), encoding="utf-8")

        baseline = len(harness.runner.calls)
        with mock.patch.object(store_cli, "resolve_cli_context", side_effect=bound_resolve), \
                mock.patch.object(store_cli, "LarkCli", side_effect=bound_cli):
            commands = (
                ["preflight", "--config", str(harness.config_path), "--profile", "team-a"],
                ["source-baseline", "--config", str(harness.config_path),
                 "--profile", "team-a", "--out", str(run_dir / "source_baseline.json")],
                ["prepare", "--config", str(harness.config_path),
                 "--profile", "team-a", "--run-dir", str(run_dir)],
                ["publish", "--config", str(harness.config_path),
                 "--profile", "team-a", "--run-dir", str(run_dir)],
                ["verify", "--config", str(harness.config_path),
                 "--profile", "team-a", "--run-dir", str(run_dir)],
            )
            payloads = [
                self._run_store_command(harness, command) for command in commands
            ]

        self.assertEqual([code for code, _ in payloads], [0] * len(commands))
        self.assertEqual(payloads[0][1]["status"], "read_ready")
        self.assertEqual(payloads[3][1]["published"], 1)
        self.assertEqual(payloads[4][1]["status"], "verified")
        self.assertEqual(set(profiles_seen), {"team-a"})

        operational_calls = harness.runner.calls[baseline:]
        self.assertTrue(operational_calls)
        for call in operational_calls:
            self.assertEqual(call[1:3], ["--profile", "team-a"], call)

    @staticmethod
    def _run_store_command(harness, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = store_cli.main(
                arguments, stdout=output, environ=harness.environ,
            )
        return code, json.loads(output.getvalue())

    def test_lost_resume_context_is_rejected(self):
        with self.assertRaises(setup_cli.SetupCommandError) as missing:
            setup_cli.restore_original_request(None)
        self.assertEqual(missing.exception.status, "resume_context_missing")

        with self.assertRaises(setup_cli.SetupCommandError) as incomplete:
            setup_cli.restore_original_request({
                "schema_version": 1,
                "original_request": "keep me",
                "profile": "team-a",
                "stage": "device_auth",
                "ready": False,
            })
        self.assertEqual(incomplete.exception.status, "resume_context_not_ready")


if __name__ == "__main__":
    unittest.main()
