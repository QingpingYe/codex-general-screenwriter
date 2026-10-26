import contextlib
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from models import IndexEntry
from resource_access import ResourceAccessReport

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import store_cli
from lark_cli_context import CliContext, CliContextError


def write_config(path: Path) -> None:
    path.write_text(json.dumps({
        "schema_version": 2,
        "source": {
            "space_id": "source-space",
            "root_mode": "space",
            "wiki_url": "https://example.feishu.cn/wiki/source",
        },
        "target": {"space_id": "target-space", "root_token": "root-token"},
        "identity": "user",
        "lock_ttl_minutes": 45,
    }), encoding="utf-8")


def config(path: Path):
    return SimpleNamespace(
        identity="user",
        lock_ttl_minutes=45,
        source=SimpleNamespace(space_id="preloaded-source", root_mode="space"),
        target=SimpleNamespace(root_token="root-token", space_id="target-space", root_mode="node"),
    )


class FakeCli:
    def __init__(self):
        self.listed = []
        self.fetched = []

    def list_nodes(self, space_id, parent_node_token=None, page_limit=10):
        self.listed.append(space_id)
        if parent_node_token == "root-token":
            return [{"node_token": "node-page", "title": "s/p/worldview"}]
        return []

    def preflight(self, target_root_token, root_mode="node"):
        return {"identity": "user", "root": target_root_token}

    def fetch_doc(self, doc_token):
        self.fetched.append(doc_token)
        content_by_token = {
            "index-doc": "# AI_KB_INDEX_V1\n```json\n{\"schema_version\":1,\"entries\":[]}\n```\n",
            "page-doc": "# 世界观\n\n正文\n",
            "admission-doc": "# AI_KB_SOURCE_ADMISSION_V1\n```json\n{\"schema_version\":1,\"entries\":[]}\n```\n",
        }
        revision_by_token = {"index-doc": 2, "page-doc": 4, "admission-doc": 3}
        return {"data": {"document": {
            "revision_id": revision_by_token[doc_token],
            "content": content_by_token[doc_token],
        }}}


class FakePublisher:
    def __init__(self, tokens=None, error=None):
        self.tokens = tokens or {"index": "index-doc", "lock": "lock-doc"}
        self.error = error
        self.resolve_calls = 0

    def inspect_control_tree(self):
        return {
            "status": "control_tree_complete",
            "state": "complete",
            "present": ["00_使用说明"],
            "missing": [],
            "duplicates": [],
            "tokens": {"index": "index-doc", "lock": "lock-doc"},
        }

    def resolve_control_plane(self):
        self.resolve_calls += 1
        if self.error:
            raise self.error
        return self.tokens


class FakeControlPlane:
    def __init__(self):
        self.acquired = []
        self.released = []

    def acquire_lock(self, holder, now):
        self.acquired.append(holder)
        return "lease"

    def release_lock(self, lease):
        self.released.append(lease)

    def read_lock(self):
        return 7, {"holder": None, "run_id": None}

    def read_index(self):
        return {
            "s/p/worldview": IndexEntry(
                key="s/p/worldview", doc_token="page-doc",
                wiki_node_token="node-page", source_revisions={"node": "1"},
                last_ai_revision_id=4, last_seen_revision_id=4,
                status="published",
            )
        }


def fake_factory(config_path, environ=None, workspace=None):
    return SimpleNamespace(
        config=config(Path(config_path)),
        config_path=Path(config_path),
        cli=FakeCli(),
        publisher=FakePublisher(),
        control_plane=FakeControlPlane(),
    )


def write_manifest(run_dir: Path) -> None:
    staging = run_dir / "wiki_staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "worldview.md").write_text("---\ntitle: 世界观\n---\n# 世界观\n", encoding="utf-8")
    (staging / "_manifest.json").write_text(json.dumps({
        "version": 9, "series": {}, "root": [],
        "entries": [{
            "path": "worldview.md", "key": "s/p/worldview",
            "source_revisions": {"node": "1"}, "page_type": "worldview",
            "series_id": "s", "project_id": "p",
        }],
    }), encoding="utf-8")


class StoreCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "config.json"
        write_config(self.config_path)

    def test_resolve_command_prints_control_tokens(self):
        stdout = StringIO()
        exit_code = store_cli.main(
            ["resolve", "--config", str(self.config_path)],
            stdout=stdout,
            components_factory=fake_factory,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["index"], "index-doc")

    def test_preflight_uses_user_identity_and_reports_root(self):
        stdout = StringIO()
        with patch.object(
                store_cli, "check_resource_access",
                return_value=ResourceAccessReport("ok", (), ("readable",))):
            exit_code = store_cli.main(
                ["preflight", "--config", str(self.config_path)],
                stdout=stdout,
                components_factory=fake_factory,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["identity"], "user")
        self.assertEqual(payload["root"], "root-token")

    def test_source_baseline_is_read_only_and_writes_projection(self):
        class FakeControlPlaneWithRevision(FakeControlPlane):
            def read_index_with_revision(self):
                return 7, self.read_index()

        class FakePublisherWithAdmission(FakePublisher):
            def resolve_control_plane(self, require_admission=False):
                return {
                    "index": "index-doc",
                    "lock": "lock-doc",
                    "admission": "admission-doc",
                }

        def factory(config_path, environ=None, workspace=None):
            return SimpleNamespace(
                config=config(Path(config_path)), cli=FakeCli(),
                config_path=Path(config_path),
                publisher=FakePublisherWithAdmission(),
                control_plane=FakeControlPlaneWithRevision(),
            )

        out = Path(self.tmp.name) / "source_baseline.json"
        stdout = StringIO()
        exit_code = store_cli.main([
            "source-baseline", "--config", str(self.config_path), "--out", str(out),
        ], stdout=stdout, components_factory=factory)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["index_revision_id"], 7)
        self.assertTrue(payload["admission_page_present"])
        projected = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(projected["admission"]["entries"], [])

    def test_lock_status_reads_public_lock_reader(self):
        stdout = StringIO()
        exit_code = store_cli.main(
            ["lock-status", "--config", str(self.config_path)],
            stdout=stdout,
            components_factory=fake_factory,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["revision_id"], 7)

    def test_missing_control_page_fails_closed(self):
        class MissingPublisher(FakePublisher):
            def resolve_control_plane(self):
                raise RuntimeError("missing system page: AI_KB_INDEX_V1")

        def missing_factory(config_path, environ=None, workspace=None):
            return SimpleNamespace(
                config=config(Path(config_path)), cli=FakeCli(),
                config_path=Path(config_path),
                publisher=MissingPublisher(), control_plane=FakeControlPlane(),
            )

        stdout = StringIO()
        exit_code = store_cli.main(
            ["resolve", "--config", str(self.config_path)],
            stdout=stdout,
            components_factory=missing_factory,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertIn("missing system page", payload["error"])

    def test_prepare_command_delegates_to_sync_runner(self):
        run_dir = Path(self.tmp.name) / "run-1"
        write_manifest(run_dir)
        cli = FakeCli()

        def factory(config_path, environ=None, workspace=None):
            return SimpleNamespace(
                config=config(Path(config_path)), cli=cli,
                config_path=Path(config_path),
                publisher=FakePublisher(), control_plane=FakeControlPlane(),
            )

        stdout = StringIO()
        exit_code = store_cli.main([
            "prepare", "--config", str(self.config_path), "--run-dir", str(run_dir),
        ], stdout=stdout, components_factory=factory)
        manifest = run_dir / "wiki_staging" / "_manifest.json"
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, str(manifest))
        self.assertTrue((run_dir / "source_nodes.json").exists())
        self.assertEqual(cli.listed, ["preloaded-source"])

    def test_retired_conflict_commands_are_rejected(self):
        def factory(*args, **kwargs):
            raise AssertionError("retired command must not build components")

        for command in ("conflict-list", "conflict-append"):
            with self.subTest(command=command):
                with contextlib.redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        store_cli.main(
                            [command, "--config", str(self.config_path)],
                            stdout=StringIO(), components_factory=factory,
                        )
                self.assertEqual(caught.exception.code, 2)

    def test_lint_fixture_writes_tree_index_and_pages(self):
        cli = FakeCli()

        def factory(config_path, environ=None, workspace=None):
            return SimpleNamespace(
                config=config(Path(config_path)), cli=cli,
                config_path=Path(config_path),
                publisher=FakePublisher(), control_plane=FakeControlPlane(),
            )

        out = Path(self.tmp.name) / "fixture"
        stdout = StringIO()
        exit_code = store_cli.main([
            "lint-fixture", "--config", str(self.config_path), "--out", str(out),
        ], stdout=stdout, components_factory=factory)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["out"], str(out))
        self.assertTrue((out / "tree.json").exists())
        self.assertTrue((out / "index.md").exists())
        self.assertFalse((out / "conflict.md").exists())
        self.assertTrue((out / "pages" / "s__p__worldview.md").exists())
        self.assertEqual(cli.fetched, ["index-doc", "page-doc"])

    def test_components_use_workspace_without_explicit_config(self):
        workspace = Path(self.tmp.name)
        workspace_config = workspace / "feishu-knowledge-base.json"
        write_config(workspace_config)
        seen = {}

        def factory(config_path, environ=None, workspace=None):
            seen.update(config_path=config_path, workspace=workspace)
            return SimpleNamespace(
                config=config(workspace_config), cli=FakeCli(),
                publisher=FakePublisher(), control_plane=FakeControlPlane(),
            )

        stdout = StringIO()
        exit_code = store_cli.main(
            ["resolve", "--workspace", str(workspace)],
            stdout=stdout, components_factory=factory,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(seen["workspace"], workspace)

    def test_missing_config_error_is_machine_readable(self):
        stdout = StringIO()
        missing = Path(self.tmp.name) / "missing.json"
        with patch.dict(os.environ, {"PICTUREBOOK_KB_CONFIG": str(missing)}):
            exit_code = store_cli.main(
                ["resolve", "--workspace", str(self.tmp.name)],
                stdout=stdout,
                components_factory=store_cli.build_components,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "missing_config")
        self.assertIn("searched", payload)

    def test_build_components_uses_one_resolved_context_and_profile(self):
        resolved = SimpleNamespace(
            path=self.config_path,
            origin="explicit",
            searched=(self.config_path,),
        )
        context = SimpleNamespace(
            binary=Path(r"C:\工具 目录\lark-cli.exe"),
            version="1.0.95",
            profile="team-a",
            capabilities=frozenset({"help", "wiki"}),
        )
        seen = {}

        class FakeCli:
            def __init__(self, binary, identity="user", runner=None, profile=None):
                seen["cli"] = (binary, identity, profile)

        class FakePublisher:
            def __init__(self, cli, root_token, space_id, root_mode=None):
                seen["publisher"] = (cli, root_token, space_id, root_mode)

            def resolve_control_plane(self):
                return {"index": "index-doc", "lock": "lock-doc"}

        class FakeControlPlane:
            def __init__(self, cli, tokens, lock_ttl_minutes=None):
                seen["control_plane"] = (cli, tokens, lock_ttl_minutes)

        def resolve_context(**kwargs):
            seen["context_call"] = kwargs
            return context

        with patch.object(store_cli, "resolve_config_path", return_value=resolved), \
                patch.object(store_cli, "load_config", return_value=config(self.config_path)), \
                patch.object(store_cli, "resolve_cli_context", side_effect=resolve_context), \
                patch.object(store_cli, "LarkCli", FakeCli), \
                patch.object(store_cli, "Publisher", FakePublisher), \
                patch.object(store_cli, "ControlPlane", FakeControlPlane):
            components = store_cli.build_components(
                config_path=self.config_path,
                environ={"TEST_ENV": "1"},
                profile="team-a",
            )

        self.assertIs(components.cli_context, context)
        self.assertEqual(seen["cli"], (context.binary, "user", "team-a"))
        self.assertEqual(seen["context_call"]["profile"], "team-a")
        self.assertEqual(seen["context_call"]["environ"], {"TEST_ENV": "1"})

    def test_config_status_reports_missing_configuration(self):
        stdout = StringIO()
        missing = Path(self.tmp.name) / "missing.json"
        context = CliContext(
            Path(r"D:\lark-cli\lark-cli.exe"),
            "1.0.95",
            None,
            frozenset({"help"}),
        )
        with patch.dict(os.environ, {"PICTUREBOOK_KB_CONFIG": str(missing)}), \
                patch.object(store_cli, "resolve_cli_context", return_value=context):
            exit_code = store_cli.main(
                ["config-status", "--workspace", str(self.tmp.name)],
                stdout=stdout,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["status"], "missing_config")
        self.assertEqual(payload["cli_status"]["version"], "1.0.95")
        self.assertEqual(payload["cli_status"]["status"], "available")

    def test_config_status_reports_placeholder_without_remote_calls(self):
        placeholder_path = Path(self.tmp.name) / "placeholder.json"
        placeholder_path.write_text(json.dumps({
            "schema_version": 2,
            "source": {
                "space_id": "source-space", "root_mode": "space",
                "wiki_url": "https://example.feishu.cn/wiki/source",
            },
            "target": {"space_id": "target-space",
                       "root_token": "REPLACE_WITH_TARGET_ROOT_TOKEN"},
            "identity": "user", "lock_ttl_minutes": 45,
        }), encoding="utf-8")
        stdout = StringIO()
        missing = Path(self.tmp.name) / "missing.json"
        context = CliContext(
            Path(r"D:\lark-cli\lark-cli.exe"),
            "1.0.95",
            None,
            frozenset({"help"}),
        )
        with patch.dict(os.environ, {"PICTUREBOOK_KB_CONFIG": str(missing)}), \
                patch.object(store_cli, "resolve_cli_context", return_value=context):
            exit_code = store_cli.main(
                ["config-status", "--config", str(placeholder_path)],
                stdout=stdout,
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["status"], "placeholder_target_token")
        self.assertNotIn("root-token", stdout.getvalue())

    def test_config_status_reports_invalid_explicit_path_consistently(self):
        stale = Path(r"C:\工具 目录\lark-cli.exe")
        error = CliContextError(
            f"lark-cli path is unusable: {stale} (executable not found)",
            status="cli_missing",
            path=stale,
            reason="executable not found",
            searched=(stale,),
        )
        stdout = StringIO()
        with patch.object(store_cli, "resolve_cli_context", side_effect=error) as resolver:
            exit_code = store_cli.main(
                ["config-status", "--config", str(self.config_path)],
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["cli_status"]["status"], "cli_missing")
        self.assertEqual(payload["cli_status"]["path"], str(stale))
        self.assertIn("not found", payload["cli_status"]["reason"])
        self.assertNotIn("candidates", resolver.call_args.kwargs)
        self.assertIsNone(resolver.call_args.kwargs["environ"])

    def test_config_status_delegates_full_default_candidate_resolution(self):
        private_context = CliContext(
            Path(r"C:\Users\writer\AppData\Local\general-screenwriter\runtimes\lark-cli\1.0.95\node_modules\.bin\lark-cli.cmd"),
            "1.0.95",
            None,
            frozenset({"help", "wiki"}),
        )
        stdout = StringIO()
        with patch.object(store_cli, "resolve_cli_context", return_value=private_context) as resolver:
            exit_code = store_cli.main(
                ["config-status", "--config", str(self.config_path)],
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["cli_status"]["path"], str(private_context.binary))
        self.assertEqual(payload["cli_status"]["status"], "available")
        self.assertNotIn("candidates", resolver.call_args.kwargs)
        self.assertIsNone(resolver.call_args.kwargs["environ"])

    def test_documented_operator_commands_use_store_cli(self):
        repo_root = Path(__file__).parents[5]
        text = (repo_root / "README.md").read_text(encoding="utf-8")
        for command in ("source-baseline", "prepare", "publish", "verify"):
            with self.subTest(command=command):
                self.assertNotIn(f"sync_runner.py {command}", text)
                self.assertIn(f"store_cli.py {command}", text)

    def test_unknown_command_is_reported_instead_of_crashing(self):
        parser = SimpleNamespace(parse_args=lambda argv: SimpleNamespace(
            command="future-command", config=None, workspace=None,
        ))
        stdout = StringIO()
        with patch.object(store_cli, "build_parser", return_value=parser):
            exit_code = store_cli.main(
                ["future-command"], stdout=stdout,
                components_factory=lambda *args, **kwargs: SimpleNamespace(),
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "unsupported_command")
        self.assertEqual(payload["command"], "future-command")

    def test_preflight_does_not_resolve_or_load_the_control_plane(self):
        publisher = FakePublisher()

        def factory(config_path, environ=None, workspace=None):
            return SimpleNamespace(
                config=config(Path(config_path)), config_path=Path(config_path),
                cli=FakeCli(), publisher=publisher,
                control_plane=AssertionError("preflight must not load ControlPlane"),
            )

        stdout = StringIO()
        with patch.object(
                store_cli, "check_resource_access",
                return_value=ResourceAccessReport("ok", (), ("readable",))):
            exit_code = store_cli.main(
                ["preflight", "--config", str(self.config_path)],
                stdout=stdout,
                components_factory=factory,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "read_ready")
        self.assertEqual(payload["identity"], "user")
        self.assertEqual(payload["root"], "root-token")
        self.assertEqual(payload["control_tree"]["status"], "control_tree_complete")
        self.assertEqual(publisher.resolve_calls, 0)

    def test_doctor_command_does_not_build_eager_components(self):
        seen = {}

        def doctor(**kwargs):
            seen.update(kwargs)
            return {"schema_version": 1, "status": "waiting_initializer", "ready": False, "checks": []}

        stdout = StringIO()
        with patch.object(
                store_cli, "build_components",
                side_effect=AssertionError("doctor must not build the control plane")):
            with patch.object(store_cli, "run_doctor", side_effect=doctor):
                exit_code = store_cli.main(
                    ["doctor", "--config", str(self.config_path), "--initializer"],
                    stdout=stdout,
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "waiting_initializer")
        self.assertEqual(seen["config_path"], str(self.config_path))
        self.assertTrue(seen["initializer"])

    def test_profile_bound_setup_commands_pass_the_explicit_profile(self):
        seen = []
        report = {"status": "ready", "ready": True, "checks": []}
        with patch.object(
                store_cli, "run_doctor",
                side_effect=lambda **kwargs: seen.append(kwargs) or report):
            store_cli.main([
                "doctor", "--config", str(self.config_path),
                "--profile", "team-z",
            ], stdout=StringIO())
        with patch.object(
                store_cli, "init_target",
                side_effect=lambda **kwargs: seen.append(kwargs) or report):
            store_cli.main([
                "init-target", "--config", str(self.config_path),
                "--profile", "team-z", "--initializer", "--authorized",
            ], stdout=StringIO())
        with patch.object(
                store_cli, "verify_write_access",
                side_effect=lambda **kwargs: seen.append(kwargs) or report):
            store_cli.main([
                "write-verify", "--config", str(self.config_path),
                "--profile", "team-z", "--authorized",
            ], stdout=StringIO())

        self.assertEqual([item["profile"] for item in seen], ["team-z"] * 3)
    def test_init_target_command_passes_initializer_and_authorization(self):
        seen = {}

        def initialize(**kwargs):
            seen.update(kwargs)
            return {"status": "write_verification_required", "ready": False, "checks": []}

        stdout = StringIO()
        with patch.object(
                store_cli, "build_components",
                side_effect=AssertionError("init-target must not build the control plane")):
            with patch.object(store_cli, "init_target", side_effect=initialize):
                exit_code = store_cli.main([
                    "init-target", "--config", str(self.config_path),
                    "--initializer", "--authorized",
                ], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "write_verification_required")
        self.assertTrue(seen["initializer_confirmed"])
        self.assertTrue(seen["authorized"])

    def test_write_verify_command_passes_authorization(self):
        seen = {}

        def verify(**kwargs):
            seen.update(kwargs)
            return {"status": "ready", "ready": True, "checks": []}

        stdout = StringIO()
        with patch.object(
                store_cli, "build_components",
                side_effect=AssertionError("write-verify must not build a sync control plane")):
            with patch.object(store_cli, "verify_write_access", side_effect=verify):
                exit_code = store_cli.main([
                    "write-verify", "--config", str(self.config_path), "--authorized",
                ], stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ready"])
        self.assertTrue(seen["authorized"])

    def test_build_read_components_stops_before_control_plane(self):
        resolved = SimpleNamespace(
            path=self.config_path, origin="explicit", searched=(self.config_path,),
        )
        context = SimpleNamespace(
            binary=Path(r"C:\工具 目录\lark-cli.exe"), version="1.0.95",
            profile="team-a", capabilities=frozenset({"help", "wiki"}),
        )
        seen = {}

        class FakeCli:
            def __init__(self, binary, identity="user", runner=None, profile=None):
                seen["cli"] = (binary, identity, profile)

        class FakePublisher:
            def __init__(self, cli, root_token, space_id, root_mode=None):
                seen["publisher"] = (cli, root_token, space_id, root_mode)

        with patch.object(store_cli, "resolve_config_path", return_value=resolved), \
                patch.object(store_cli, "load_config", return_value=config(self.config_path)), \
                patch.object(store_cli, "resolve_cli_context", return_value=context), \
                patch.object(store_cli, "LarkCli", FakeCli), \
                patch.object(store_cli, "Publisher", FakePublisher), \
                patch.object(
                    store_cli, "ControlPlane",
                    side_effect=AssertionError("read-only components must not load ControlPlane")):
            components = store_cli.build_read_components(
                config_path=self.config_path, environ={"TEST_ENV": "1"},
                profile="team-a",
            )

        self.assertEqual(seen["cli"], (context.binary, "user", "team-a"))
        self.assertEqual(seen["publisher"][1:], ("root-token", "target-space", "node"))
        self.assertFalse(hasattr(components, "control_plane"))
if __name__ == "__main__":
    unittest.main()
