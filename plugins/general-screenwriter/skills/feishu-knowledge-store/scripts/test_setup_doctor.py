import json
import sys
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lark_cli_context import CliContext, CliContextError
from lark_cli_contract import REQUIRED_CAPABILITIES
from models import KnowledgeConfig, SourceConfig, TargetConfig
from lark_profile import ProfileState
from publisher import Publisher
from resource_access import ResourceAccessReport


SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import setup_doctor
from setup_doctor import run_doctor, init_target, verify_write_access


def config():
    return KnowledgeConfig(
        SourceConfig("source-space", "space", "https://example.feishu.cn/wiki/space/source"),
        TargetConfig("target-space", "root", "node"),
        "user",
        45,
        (),
    )


def space_config():
    return KnowledgeConfig(
        SourceConfig("source-space", "space", "https://example.feishu.cn/wiki/space/source"),
        TargetConfig("target-space", None, "space"),
        "user",
        45,
        (),
    )


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class FakeCli:
    def __init__(self):
        self.nodes = {"root": []}
        self.open_id = "ou_current_user"
        self.docs = {}
        self.titles_by_token = {}
        self.created_titles = []
        self.create_attempts = {}
        self.update_calls = []
        self.fail_after_create_titles = set()
        self.fail_create_titles = set()
        self.fail_fetch_titles = set()
        self._next = 0

    def _json(self, *arguments):
        if arguments[:2] == ("auth", "status"):
            return {"data": {"user": {"open_id": self.open_id}}}
        raise AssertionError(f"unexpected command: {arguments}")

    def _new_ids(self):
        self._next += 1
        return f"doc-{self._next}", f"node-{self._next}"

    def _record(self, parent, title, content):
        doc_token, node_token = self._new_ids()
        self.created_titles.append(title)
        self.create_attempts[title] = self.create_attempts.get(title, 0) + 1
        self.nodes.setdefault(parent, []).append({
            "title": title,
            "node_token": node_token,
        })
        document = {"revision_id": 3, "content": content}
        self.docs[doc_token] = dict(document)
        self.docs[node_token] = dict(document)
        self.titles_by_token[doc_token] = title
        self.titles_by_token[node_token] = title
        return doc_token, node_token

    def list_nodes(self, space_id, parent_node_token=None, page_limit=10):
        return [dict(node) for node in self.nodes.get(parent_node_token, [])]

    def create_doc(self, parent_node_token, title, content=""):
        if title in self.fail_create_titles:
            raise RuntimeError(f"create failed before write: {title}")
        doc_token, _ = self._record(parent_node_token, title, content)
        if title in self.fail_after_create_titles:
            raise TimeoutError(f"create timed out after writing: {title}")
        return {"code": 0, "data": {"document": {
            "document_id": doc_token,
            "revision_id": 3,
        }}}

    def create_space_doc(self, space_id, title, content=""):
        return self.create_doc(None, title, content)

    def fetch_doc(self, doc_token):
        title = self.titles_by_token.get(doc_token)
        if title in self.fail_fetch_titles:
            raise TimeoutError(f"readback timed out: {doc_token}")
        if doc_token not in self.docs:
            raise RuntimeError(f"unknown document: {doc_token}")
        return {"data": {"document": dict(self.docs[doc_token])}}

    def update_doc(self, doc_token, revision_id, content):
        if doc_token not in self.docs:
            raise RuntimeError(f"unknown document: {doc_token}")
        self.update_calls.append((doc_token, revision_id, content))
        document = self.docs[doc_token]
        if document["revision_id"] != revision_id:
            raise RuntimeError("revision conflict")
        document["revision_id"] = revision_id + 2
        document["content"] = content
        return {"code": 0, "data": {"document": {
            "revision_id": document["revision_id"],
        }}}


@contextmanager
def patched_runtime(
    cli=None,
    *,
    config_obj=None,
    context=None,
    cli_error=None,
    resource_report=None,
):
    cli = cli or FakeCli()
    config_obj = config_obj or config()
    context = context or CliContext(
        Path("lark-cli"), "1.0.95", "team-a", frozenset(REQUIRED_CAPABILITIES),
    )
    resolved = SimpleNamespace(
        path=Path("C:/tmp/feishu-knowledge-base.json"),
        origin="explicit",
        searched=(Path("C:/tmp/feishu-knowledge-base.json"),),
    )
    if resource_report is None:
        resource_report = ResourceAccessReport("ok", (), ("verified",))
    with ExitStack() as stack:
        stack.enter_context(patch.object(
            setup_doctor, "resolve_config_path", return_value=resolved,
        ))
        stack.enter_context(patch.object(
            setup_doctor, "load_config", return_value=config_obj,
        ))
        cli_resolver = stack.enter_context(patch.object(
            setup_doctor, "resolve_cli_context",
        ))
        if cli_error is not None:
            cli_resolver.side_effect = cli_error
        else:
            cli_resolver.return_value = context
        stack.enter_context(patch.object(setup_doctor, "LarkCli", return_value=cli))
        stack.enter_context(patch.object(
            setup_doctor, "check_resource_access", return_value=resource_report,
        ))
        stack.enter_context(patch.object(
            setup_doctor,
            "ensure_named_profile",
            return_value=ProfileState(
                context.profile or "general-screenwriter", "cli_test_app", "existing",
            ),
        ))

        yield SimpleNamespace(cli=cli, resolver=cli_resolver)


def check(report, check_id):
    return next(item for item in report["checks"] if item["check_id"] == check_id)


class SetupDoctorTests(unittest.TestCase):
    def test_explicit_profile_is_forwarded_to_cli_resolution(self):
        context = CliContext(
            Path("lark-cli"), "1.0.95", "team-z", frozenset(REQUIRED_CAPABILITIES),
        )
        resolved = SimpleNamespace(
            path=Path("C:/tmp/feishu-knowledge-base.json"),
            origin="explicit",
            searched=(Path("C:/tmp/feishu-knowledge-base.json"),),
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                setup_doctor, "resolve_config_path", return_value=resolved,
            ))
            stack.enter_context(patch.object(
                setup_doctor, "load_config", return_value=config(),
            ))
            resolver = stack.enter_context(patch.object(
                setup_doctor, "resolve_cli_context", return_value=context,
            ))
            stack.enter_context(patch.object(setup_doctor, "LarkCli", return_value=FakeCli()))
            stack.enter_context(patch.object(
                setup_doctor, "Publisher", return_value=SimpleNamespace(
                    inspect_control_tree=lambda: {
                        "status": "control_tree_complete",
                        "state": "complete",
                        "present": [],
                        "missing": [],
                        "duplicates": [],
                        "tokens": {},
                        "verification_token": None,
                    },
                ),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "ensure_named_profile",
                return_value=ProfileState("team-z", "cli_app", "existing"),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "read_authenticated_identity", return_value="open_id:ou_user",
            ))
            stack.enter_context(patch.object(
                setup_doctor, "check_resource_access",
                return_value=ResourceAccessReport("ok", (), ("verified",)),
            ))
            run_doctor(config_path="config.json", profile="team-z")

        self.assertEqual(resolver.call_args.kwargs["profile"], "team-z")

    def test_profile_continuity_across_doctor_init_and_write_verify(self):
        cli = FakeCli()
        with patched_runtime(cli) as runtime:
            run_doctor(config_path="config.json", profile="team-z")
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
                profile="team-z",
            )
            verify_write_access(
                config_path="config.json",
                authorized=True,
                profile="team-z",
            )

        profiles = [
            call.kwargs.get("profile")
            for call in runtime.resolver.call_args_list
        ]
        self.assertTrue(profiles)
        self.assertEqual(set(profiles), {"team-z"})
    def test_missing_scope_reports_permission_missing(self):
        report = None
        with patched_runtime(resource_report=ResourceAccessReport(
                "permission_missing", ("scope:docs:permission.member:auth",),
                ("target edit permission needs an application scope",))):
            report = run_doctor(config_path="config.json", profile="team-a")

        self.assertEqual(report["status"], "permission_missing")
        self.assertEqual(check(report, "resource_access")["status"], "permission_missing")
        self.assertIn(
            "scope:docs:permission.member:auth",
            report["resource_access"]["missing"],
        )

    def test_duplicate_profile_entries_report_profile_ambiguous(self):
        profiles = json.dumps([
            {"name": "team-a", "appId": "cli_one"},
            {"name": "team-a", "appId": "cli_two"},
        ])

        def profile_runner(command, **_kwargs):
            if list(command)[-2:] == ["profile", "list"]:
                return Completed(profiles)
            raise AssertionError(f"unexpected command: {command}")

        with ExitStack() as stack:
            stack.enter_context(patch.object(
                setup_doctor, "resolve_config_path",
                return_value=SimpleNamespace(
                    path=Path("C:/tmp/feishu-knowledge-base.json"),
                    origin="explicit",
                    searched=(Path("C:/tmp/feishu-knowledge-base.json"),),
                ),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "load_config", return_value=config(),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "resolve_cli_context",
                return_value=CliContext(
                    Path("lark-cli"), "1.0.95", "team-a",
                    frozenset(REQUIRED_CAPABILITIES),
                ),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "LarkCli", return_value=FakeCli(),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "check_resource_access",
                return_value=ResourceAccessReport("ok", (), ("verified",)),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "Publisher", return_value=SimpleNamespace(
                    inspect_control_tree=lambda: {
                        "status": "control_tree_missing",
                        "state": "missing",
                        "present": [],
                        "missing": list(setup_doctor.TREE_ORDER),
                        "duplicates": [],
                        "tokens": {},
                        "verification_token": None,
                    },
                ),
            ))
            report = run_doctor(
                config_path="config.json", profile="team-a", runner=profile_runner,
            )

        self.assertEqual(report["status"], "profile_ambiguous")
        self.assertEqual(check(report, "profile")["status"], "profile_ambiguous")
        self.assertEqual(check(report, "app")["status"], "needs_context")
        self.assertFalse(any(
            item["status"] == "ready" and item["check_id"] in {"profile", "app"}
            for item in report["checks"]
        ))

    def test_run_doctor_uses_setup_default_profile_when_none_is_supplied(self):
        context = CliContext(
            Path("lark-cli"), "1.0.95", None,
            frozenset(REQUIRED_CAPABILITIES),
        )
        missing_config = setup_doctor.ConfigResolutionError(
            "configuration file not found",
            status="missing_config",
        )
        with (
            patch.object(
                setup_doctor, "_resolve_cli_runtime",
                return_value=(context, FakeCli()),
            ) as resolve_runtime,
            patch.object(setup_doctor, "resolve_config_path", side_effect=missing_config),
            patch.object(
                setup_doctor, "ensure_named_profile",
                return_value=ProfileState(
                    setup_doctor.DEFAULT_PROFILE, "cli_app", "existing",
                ),
            ),
            patch.object(
                setup_doctor, "read_authenticated_identity",
                return_value="open_id:ou_user",
            ),
        ):
            run_doctor(config_path="config.json")

        self.assertEqual(
            resolve_runtime.call_args.args[0],
            setup_doctor.DEFAULT_PROFILE,
        )
    def test_no_config_doctor_reports_independent_prerequisite_checks(self):
        context = CliContext(
            Path("lark-cli"), "1.0.95", "team-z", frozenset(REQUIRED_CAPABILITIES),
        )
        missing_config = setup_doctor.ConfigResolutionError(
            "configuration file not found",
            status="missing_config",
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                setup_doctor, "resolve_config_path", side_effect=missing_config,
            ))
            stack.enter_context(patch.object(
                setup_doctor, "resolve_cli_context", return_value=context,
            ))
            stack.enter_context(patch.object(setup_doctor, "LarkCli", return_value=FakeCli()))
            stack.enter_context(patch.object(
                setup_doctor, "ensure_named_profile",
                return_value=ProfileState("team-z", "cli_app", "existing"),
            ))
            stack.enter_context(patch.object(
                setup_doctor, "read_authenticated_identity", return_value="open_id:ou_user",
            ))
            resource = stack.enter_context(patch.object(
                setup_doctor, "check_resource_access",
            ))
            report = run_doctor(config_path="config.json", profile="team-z")

        check_ids = [item["check_id"] for item in report["checks"]]
        self.assertEqual(report["status"], "config_missing")
        self.assertEqual(
            check_ids,
            [
                "config", "runtime", "cli", "profile", "app", "auth",
                "resource_access", "control_tree", "write_verification",
            ],
        )
        self.assertEqual(check(report, "config")["reason_code"], "missing_config")
        self.assertEqual(check(report, "resource_access")["reason_code"], "config_missing")
        self.assertEqual(check(report, "control_tree")["reason_code"], "config_missing")
        self.assertEqual(check(report, "write_verification")["reason_code"], "config_missing")
        resource.assert_not_called()
    def test_empty_target_doctor_waits_without_control_plane_or_lock(self):
        cli = FakeCli()
        with patched_runtime(cli), \
                patch.object(Publisher, "resolve_control_plane", side_effect=AssertionError(
                    "doctor must not resolve the control plane"
                )), \
                patch.object(setup_doctor, "ControlPlane", side_effect=AssertionError(
                    "doctor must not load ControlPlane"
                )):
            report = run_doctor(config_path="config.json", initializer=False)

        self.assertEqual(report["status"], "waiting_initializer")
        self.assertEqual(check(report, "control_tree")["reason_code"], "control_tree_missing")
        self.assertEqual(cli.created_titles, [])

    def test_designated_initializer_doctor_reports_missing_control_tree(self):
        with patched_runtime():
            report = run_doctor(config_path="config.json", initializer=True)

        self.assertEqual(report["status"], "control_tree_missing")
        self.assertEqual(check(report, "control_tree")["status"], "control_tree_missing")

    def test_doctor_maps_cli_version_and_capability_failures(self):
        with patched_runtime(cli_error=CliContextError(
                "old", status="unsupported_version")):
            old = run_doctor(config_path="config.json")
        self.assertEqual(old["status"], "cli_too_old")

        missing_caps = CliContext(Path("lark-cli"), "1.0.95", "team-a", frozenset())
        with patched_runtime(context=missing_caps):
            missing = run_doctor(config_path="config.json")
        self.assertEqual(missing["status"], "capability_missing")
        self.assertIn("docs", check(missing, "cli")["message"])

    def test_init_target_requires_initializer_confirmation_with_zero_writes(self):
        cli = FakeCli()
        with patched_runtime(cli):
            report = init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=False,
            )

        self.assertEqual(report["status"], "waiting_initializer")
        self.assertEqual(cli.created_titles, [])
        self.assertEqual(cli.update_calls, [])

    def test_init_target_requires_explicit_write_authorization(self):
        cli = FakeCli()
        with patched_runtime(cli):
            report = init_target(
                config_path="config.json",
                authorized=False,
                initializer_confirmed=True,
            )

        self.assertEqual(report["status"], "needs_escalation")
        self.assertEqual(cli.created_titles, [])

    def test_init_target_previews_initializes_reads_back_and_is_idempotent(self):
        cli = FakeCli()
        with patched_runtime(cli):
            first = init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            created = list(cli.created_titles)
            second = init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )

        self.assertEqual(first["status"], "write_verification_required")
        self.assertEqual(second["status"], "write_verification_required")
        self.assertEqual(second["preview"]["status"], "already_initialized")
        self.assertEqual(cli.created_titles, created)
        self.assertEqual(len(created), 9)
        self.assertEqual(first["control_tree"]["status"], "control_tree_complete")

    def test_init_target_stops_on_partial_or_duplicate_system_pages(self):
        partial = FakeCli()
        partial.nodes["root"] = [{"title": "00_使用说明", "node_token": "node-partial"}]
        with patched_runtime(partial):
            partial_report = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )

        duplicate = FakeCli()
        duplicate.nodes["root"] = [
            {"title": "00_使用说明", "node_token": "node-a"},
            {"title": "00_使用说明", "node_token": "node-b"},
        ]
        with patched_runtime(duplicate):
            duplicate_report = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )

        self.assertEqual(partial_report["status"], "control_tree_ambiguous")
        self.assertEqual(duplicate_report["status"], "control_tree_ambiguous")
        self.assertEqual(partial.created_titles, [])
        self.assertEqual(duplicate.created_titles, [])

    def test_init_target_uncertain_create_reads_back_without_blind_retry(self):
        cli = FakeCli()
        cli.fail_after_create_titles = {"00_使用说明"}
        with patched_runtime(cli):
            report = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )

        self.assertEqual(report["status"], "write_result_uncertain")
        self.assertEqual(cli.create_attempts["00_使用说明"], 1)
        self.assertEqual(report["readback"]["state"], "incomplete")

    def test_ready_requires_a_successful_write_verification(self):
        cli = FakeCli()
        with patched_runtime(cli):
            initialized = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )
            before = run_doctor(config_path="config.json")
            verified = verify_write_access(config_path="config.json", authorized=True)
            after = run_doctor(config_path="config.json")

        self.assertEqual(initialized["status"], "write_verification_required")
        self.assertEqual(before["status"], "write_verification_required")
        self.assertEqual(verified["status"], "ready")
        self.assertEqual(after["status"], "ready")
        self.assertIn(setup_doctor.WRITE_VERIFICATION_TITLE, cli.created_titles)

    def test_verify_write_access_requires_authorization(self):
        cli = FakeCli()
        with patched_runtime(cli):
            initialized = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )
            created = len(cli.created_titles)
            report = verify_write_access(config_path="config.json", authorized=False)

        self.assertEqual(initialized["status"], "write_verification_required")
        self.assertEqual(report["status"], "needs_escalation")
        self.assertEqual(len(cli.created_titles), created)

    def test_uncertain_verification_create_is_recovered_by_readback_once(self):
        cli = FakeCli()
        with patched_runtime(cli):
            init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )
            cli.fail_after_create_titles = {setup_doctor.WRITE_VERIFICATION_TITLE}
            report = verify_write_access(config_path="config.json", authorized=True)

        self.assertEqual(report["status"], "ready")
        self.assertEqual(cli.create_attempts[setup_doctor.WRITE_VERIFICATION_TITLE], 1)

    def test_unreadable_verification_write_returns_uncertain(self):
        cli = FakeCli()
        with patched_runtime(cli):
            init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )
            cli.fail_fetch_titles = {setup_doctor.WRITE_VERIFICATION_TITLE}
            report = verify_write_access(config_path="config.json", authorized=True)

        self.assertEqual(report["status"], "write_result_uncertain")

    def test_space_root_resource_grant_is_resolved_by_verified_acceptance_write(self):
        cli = FakeCli()
        resource_grant = ResourceAccessReport(
            "resource_grant_required",
            ("target.create", "target.acceptance_write"),
            ("root-level create cannot be proven read-only",),
        )
        with patched_runtime(
            cli,
            config_obj=space_config(),
            resource_report=resource_grant,
        ):
            initialized = init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            verified = verify_write_access(
                config_path="config.json",
                authorized=True,
            )
            final = run_doctor(config_path="config.json")

        self.assertEqual(initialized["status"], "write_verification_required")
        self.assertEqual(verified["status"], "ready")
        self.assertEqual(final["status"], "ready")
        self.assertTrue(final["ready"])
        self.assertEqual(final["resource_access"]["status"], "ok")
        self.assertEqual(
            final["resource_access"]["read_only_status"],
            "resource_grant_required",
        )

    def test_write_verification_marker_is_bound_to_authenticated_identity(self):
        cli = FakeCli()
        cli.open_id = "ou_first_user"
        with patched_runtime(cli):
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            verify_write_access(config_path="config.json", authorized=True)
            cli.open_id = "ou_second_user"
            report = run_doctor(config_path="config.json")

        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "write_verification_required")
        self.assertEqual(
            check(report, "write_verification")["status"],
            "write_verification_required",
        )

    def test_verify_write_access_readback_exception_is_uncertain(self):
        cli = FakeCli()
        with patched_runtime(cli):
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            original_inspect = Publisher.inspect_control_tree
            calls = {"count": 0}

            def flaky_inspect(self):
                calls["count"] += 1
                if calls["count"] == 1:
                    return original_inspect(self)
                raise TimeoutError("readback unavailable")

            with patch.object(Publisher, "inspect_control_tree", flaky_inspect):
                report = verify_write_access(
                    config_path="config.json",
                    authorized=True,
                )

        self.assertEqual(report["status"], "write_result_uncertain")
        self.assertEqual(calls["count"], 2)

    def test_init_target_readback_exception_is_uncertain(self):
        cli = FakeCli()
        cli.fail_after_create_titles = {"00_使用说明"}
        with patched_runtime(cli):
            original_inspect = Publisher.inspect_control_tree
            calls = {"count": 0}

            def flaky_inspect(self):
                calls["count"] += 1
                if calls["count"] <= 2:
                    return original_inspect(self)
                raise TimeoutError("readback unavailable")

            with patch.object(Publisher, "inspect_control_tree", flaky_inspect):
                report = init_target(
                    config_path="config.json",
                    authorized=True,
                    initializer_confirmed=True,
                )

        self.assertEqual(report["status"], "write_result_uncertain")
        self.assertEqual(cli.create_attempts["00_使用说明"], 1)

    def test_verify_write_access_requires_a_stable_identity_before_writing(self):
        cli = FakeCli()
        with patched_runtime(cli):
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            cli.open_id = None
            created = len(cli.created_titles)
            updates = len(cli.update_calls)
            report = verify_write_access(config_path="config.json", authorized=True)

        self.assertEqual(report["status"], "needs_escalation")
        self.assertEqual(len(cli.created_titles), created)
        self.assertEqual(len(cli.update_calls), updates)

    def test_unrelated_resource_grant_is_not_hidden_by_write_acceptance(self):
        cli = FakeCli()
        resource_grant = ResourceAccessReport(
            "resource_grant_required",
            ("source.sample",),
            ("source sample is not readable",),
        )
        with patched_runtime(
            cli,
            config_obj=space_config(),
            resource_report=resource_grant,
        ):
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            verify_write_access(config_path="config.json", authorized=True)
            report = run_doctor(config_path="config.json")

        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "resource_grant_required")

    def test_malformed_verification_readback_is_uncertain(self):
        cli = FakeCli()
        with patched_runtime(cli):
            init_target(
                config_path="config.json",
                authorized=True,
                initializer_confirmed=True,
            )
            original_fetch = cli.fetch_doc

            def malformed_fetch(token):
                document = original_fetch(token)["data"]["document"]
                if cli.titles_by_token.get(token) == setup_doctor.WRITE_VERIFICATION_TITLE:
                    return {"data": {"document": {"revision_id": document["revision_id"]}}}
                return {"data": {"document": document}}

            cli.fetch_doc = malformed_fetch
            report = verify_write_access(config_path="config.json", authorized=True)

        self.assertEqual(report["status"], "write_result_uncertain")

    def test_init_target_does_not_run_a_full_sync(self):
        cli = FakeCli()
        with patched_runtime(cli), \
                patch("sync_runner.SyncRunner.prepare", side_effect=AssertionError("no sync")), \
                patch("sync_runner.SyncRunner.publish", side_effect=AssertionError("no sync")):
            report = init_target(
                config_path="config.json", authorized=True, initializer_confirmed=True,
            )

        self.assertEqual(report["status"], "write_verification_required")
        self.assertNotIn("s/p/worldview", cli.created_titles)


if __name__ == "__main__":
    unittest.main()
