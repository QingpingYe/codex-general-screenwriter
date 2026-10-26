import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli import AuthenticationError, PermissionDenied
from models import KnowledgeConfig, SourceConfig, TargetConfig
from resource_access import authenticated_identity, check_resource_access


def _flag(arguments, name):
    return arguments[arguments.index(name) + 1]


class FakeCli:
    identity = "user"
    binary = Path("lark-cli")


    def __init__(self, nodes=None, permissions=None, auth_error=None, auth_result=None, docs=None):
        self.nodes = dict(nodes or {})
        self.permissions = dict(permissions or {})
        self.auth_error = auth_error
        self.auth_result = auth_result
        self.docs = set(docs or ())
        self.calls = []


    def _json(self, *arguments):
        self.calls.append(arguments)
        if arguments[:2] == ("auth", "status"):
            if self.auth_error is not None:
                raise self.auth_error
            return self.auth_result or {"data": {"user": {"open_id": "ou_current_user"}}}
        if arguments[:3] == ("drive", "permission.members", "auth"):
            key = (
                _flag(arguments, "--token"),
                _flag(arguments, "--type"),
                _flag(arguments, "--action"),
            )
            result = self.permissions.get(key)
            if isinstance(result, BaseException):
                raise result
            if result is None:
                raise AssertionError(f"unexpected permission check: {key}")
            return {"data": {"auth_result": result}}
        raise AssertionError(f"unexpected command: {arguments}")


    def get_node(self, token):
        self.calls.append(("get_node", token))
        result = self.nodes.get(token)
        if isinstance(result, BaseException):
            raise result
        if result is None:
            raise AssertionError(f"unexpected node: {token}")
        return result


    def fetch_doc(self, token):
        self.calls.append(("fetch_doc", token))
        if token not in self.docs and token not in self.nodes:
            raise AssertionError(f"unexpected document: {token}")
        return {"data": {"document": {"content": "# ok"}}}


def node_payload(space_id, node_token, obj_token):
    return {"data": {"node": {
        "space_id": space_id,
        "node_token": node_token,
        "obj_token": obj_token,
    }}}


def config(source_mode="node", target_mode="node"):
    wiki_url = "https://team.feishu.cn/wiki/source-root"
    if source_mode == "space":
        wiki_url = "https://team.feishu.cn/wiki/space/source-space"
    target_token = "target-root" if target_mode == "node" else None
    return KnowledgeConfig(
        SourceConfig("source-space", source_mode, wiki_url),
        TargetConfig("target-space", target_token, target_mode),
        "user",
        45,
        (Path("lark-cli"),),
    )


class ResourceAccessTests(unittest.TestCase):


    def test_ok_checks_auth_source_sample_target_root_and_target_edit(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "sample-node": node_payload("source-space", "sample-node", "sample-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={("target-root", "wiki", "edit"): True},
            docs={"sample-doc"},
        )
        report = check_resource_access(config(), cli, ("sample-node",))

        self.assertEqual(report.status, "ok")
        self.assertEqual(report.missing, ())
        self.assertIn(("get_node", "sample-node"), cli.calls)
        self.assertIn(("fetch_doc", "sample-doc"), cli.calls)
        permission_call = next(
            call for call in cli.calls
            if call[:3] == ("drive", "permission.members", "auth")
        )
        self.assertIn("--token", permission_call)
        self.assertIn("target-root", permission_call)
        self.assertIn("edit", permission_call)


    def test_root_readable_but_sample_node_unreadable_is_resource_grant_required(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "sample-node": PermissionDenied("node permission denied"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={("target-root", "wiki", "edit"): True},
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli, ("sample-node",))

        self.assertEqual(report.status, "resource_grant_required")
        self.assertIn("source.sample", report.missing)
        self.assertNotEqual(report.status, "ok")


    def test_missing_target_edit_acl_is_resource_grant_required(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={("target-root", "wiki", "edit"): False},
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "resource_grant_required")
        self.assertIn("target.edit", report.missing)
        self.assertIn("target.acceptance_write", report.missing)


    def test_resource_permission_denial_is_not_reported_as_scope_success(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={
                ("target-root", "wiki", "edit"): PermissionDenied("resource permission denied"),
            },
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "resource_grant_required")
        self.assertIn("target.edit", report.missing)


    def test_missing_scope_is_reported_as_waiting_admin(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={
                ("target-root", "wiki", "edit"): PermissionDenied(
                    "missing scope docs:permission.member:auth"
                ),
            },
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "waiting_admin")
        self.assertIn("scope:docs:permission.member:auth", report.missing)


    def test_user_authorization_failure_is_waiting_admin_and_separate_from_acl(self):
        cli = FakeCli(auth_error=AuthenticationError("login required; scope missing"))
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "waiting_admin")
        self.assertIn("user_authorization", report.missing)
        self.assertNotIn("target.edit", report.missing)


    def test_space_source_uses_first_child_as_sample_when_available(self):
        cli = FakeCli(
            nodes={
                "first-child": node_payload("source-space", "first-child", "first-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={("target-root", "wiki", "edit"): True},
            docs={"first-doc"},
        )
        cli.list_nodes = lambda space_id, parent_node_token=None, page_limit=10: [
            {"node_token": "first-child", "obj_token": "first-doc", "space_id": space_id}
        ]
        report = check_resource_access(config(source_mode="space"), cli)

        self.assertEqual(report.status, "ok")
        self.assertIn(("get_node", "first-child"), cli.calls)


    def test_auth_status_false_is_waiting_admin(self):
        cli = FakeCli(auth_result={"ok": False})
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "waiting_admin")
        self.assertIn("user_authorization", report.missing)


    def test_target_space_with_child_does_not_treat_child_edit_as_create_acl(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
            },
            permissions={("arbitrary-child", "wiki", "edit"): True},
            docs={"source-doc"},
        )
        cli.list_nodes = lambda space_id, parent_node_token=None, page_limit=10: [
            {"node_token": "arbitrary-child"}
        ]
        report = check_resource_access(config(target_mode="space"), cli)

        self.assertEqual(report.status, "resource_grant_required")
        self.assertIn("target.create", report.missing)
        self.assertIn("target.acceptance_write", report.missing)
        self.assertTrue(any(
            call[:3] == ("drive", "permission.members", "auth") for call in cli.calls
        ))


    def test_target_space_missing_permission_auth_scope_is_waiting_admin(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
            },
            permissions={
                ("arbitrary-child", "wiki", "edit"): PermissionDenied(
                    "missing scope docs:permission.member:auth"
                ),
            },
            docs={"source-doc"},
        )
        cli.list_nodes = lambda space_id, parent_node_token=None, page_limit=10: [
            {"node_token": "arbitrary-child"}
        ]
        report = check_resource_access(config(target_mode="space"), cli)

        self.assertEqual(report.status, "waiting_admin")
        self.assertIn("scope:docs:permission.member:auth", report.missing)
        self.assertNotIn("target.create", report.missing)


    def test_empty_target_space_is_not_false_blocked(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
            },
            permissions={("target-space", "wiki", "edit"): False},
            docs={"source-doc"},
        )
        cli.list_nodes = lambda space_id, parent_node_token=None, page_limit=10: []
        report = check_resource_access(config(target_mode="space"), cli)

        self.assertEqual(report.status, "ok")
        self.assertIn("empty", " ".join(report.details).lower())
        self.assertTrue(any(
            call[:3] == ("drive", "permission.members", "auth") for call in cli.calls
        ))


    def test_empty_target_space_missing_permission_auth_scope_is_waiting_admin(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
            },
            permissions={
                ("target-space", "wiki", "edit"): PermissionDenied(
                    "missing scope docs:permission.member:auth"
                ),
            },
            docs={"source-doc"},
        )
        cli.list_nodes = lambda space_id, parent_node_token=None, page_limit=10: []
        report = check_resource_access(config(target_mode="space"), cli)

        self.assertEqual(report.status, "waiting_admin")
        self.assertIn("scope:docs:permission.member:auth", report.missing)

    def test_target_node_space_must_match_configured_target_space(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "target-root": node_payload("other-space", "target-root", "target-doc"),
            },
            permissions={("target-root", "wiki", "edit"): True},
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli)

        self.assertEqual(report.status, "resource_grant_required")
        self.assertIn("target.root", report.missing)
        self.assertFalse(any(
            call[:3] == ("drive", "permission.members", "auth") for call in cli.calls
        ))


    def test_authenticated_identity_uses_verified_open_id(self):
        cli = FakeCli(auth_result={"data": {"user": {"open_id": "ou_verified"}}})

        self.assertEqual(authenticated_identity(cli), "open_id:ou_verified")

    def test_authenticated_identity_requires_a_stable_user_identifier(self):
        cli = FakeCli(auth_result={"data": {"user": {"name": "Writer"}}})

        self.assertIsNone(authenticated_identity(cli))

    def test_details_redact_credential_values(self):
        cli = FakeCli(
            nodes={
                "source-root": node_payload("source-space", "source-root", "source-doc"),
                "target-root": node_payload("target-space", "target-root", "target-doc"),
            },
            permissions={
                ("target-root", "wiki", "edit"): PermissionDenied(
                    "denied app_secret=shortsecret access_token=shortaccess refresh_token=shortrefresh"
                ),
            },
            docs={"source-doc"},
        )
        report = check_resource_access(config(), cli)
        rendered = " ".join(report.details)

        for secret in ("shortsecret", "shortaccess", "shortrefresh"):
            self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
