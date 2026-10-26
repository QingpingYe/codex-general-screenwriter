import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from config import load_config
from knowledge_config_bootstrap import (
    KnowledgeConfigBootstrapError,
    build_config_from_links,
    parse_wiki_reference,
    write_config_atomic,
)
from models import KnowledgeConfig, SourceConfig, TargetConfig


class FakeCli:
    def __init__(self, responses=None):
        self.identity = "user"
        self.binary = Path("lark-cli")
        self.responses = dict(responses or {})
        self.calls = []

    def get_node(self, token):
        self.calls.append(token)
        response = self.responses[token]
        if isinstance(response, BaseException):
            raise response
        return response


def node_payload(space_id, node_token, obj_token):
    return {"data": {"node": {
        "space_id": space_id,
        "node_token": node_token,
        "obj_token": obj_token,
    }}}


class WikiReferenceTests(unittest.TestCase):
    def test_parses_space_url_and_discards_query_and_fragment(self):
        reference = parse_wiki_reference(
            "https://team.feishu.cn/wiki/space/space-123?from=share#section"
        )
        self.assertEqual(reference.root_mode, "space")
        self.assertEqual(reference.space_id, "space-123")
        self.assertEqual(reference.token, "space-123")

    def test_parses_node_url_and_discards_query_and_fragment(self):
        reference = parse_wiki_reference(
            "https://team.feishu.cn/wiki/node-123?from=share#section"
        )
        self.assertEqual(reference.root_mode, "node")
        self.assertEqual(reference.token, "node-123")
        self.assertIsNone(reference.space_id)

    def test_parses_node_url_with_explicit_space_identity(self):
        reference = parse_wiki_reference(
            "https://team.feishu.cn/wiki/space/space-123/node/node-456?x=1"
        )
        self.assertEqual(reference.root_mode, "node")
        self.assertEqual(reference.space_id, "space-123")
        self.assertEqual(reference.token, "node-456")

    def test_accepts_explicit_node_token_without_guessing_space(self):
        reference = parse_wiki_reference("node:node-123")
        self.assertEqual(reference.root_mode, "node")
        self.assertEqual(reference.token, "node-123")
        self.assertIsNone(reference.space_id)

    def test_rejects_non_wiki_urls_and_ambiguous_root_modes(self):
        for value in (
            "https://team.feishu.cn/docx/doc-123",
            "https://team.feishu.cn/wiki",
            "https://team.feishu.cn/wiki/space",
        ):
            with self.subTest(value=value):
                with self.assertRaises(KnowledgeConfigBootstrapError) as caught:
                    parse_wiki_reference(value)
                self.assertEqual(caught.exception.status, "config_invalid")

    def test_rejects_conflicting_url_identity(self):
        with self.assertRaises(KnowledgeConfigBootstrapError):
            parse_wiki_reference(
                "https://team.feishu.cn/wiki/space/space-123?space_id=space-456"
            )


class BuildConfigTests(unittest.TestCase):
    def test_builds_config_from_node_links_without_asking_for_ids(self):
        source_url = "https://team.feishu.cn/wiki/source-node?from=share"
        target_url = "https://team.feishu.cn/wiki/target-node#section"
        cli = FakeCli({
            "source-node": node_payload("source-space", "source-node", "source-doc"),
            "target-node": node_payload("target-space", "target-node", "target-doc"),
        })

        config = build_config_from_links(source_url, target_url, cli)

        self.assertEqual(cli.calls, ["source-node", "target-node"])
        self.assertEqual(config.source, SourceConfig(
            "source-space", "node", source_url,
        ))
        self.assertEqual(config.target, TargetConfig(
            "target-space", "target-node", "node",
        ))
        self.assertEqual(config.identity, "user")
        self.assertEqual(config.cli_candidates, (Path("lark-cli"),))

    def test_builds_space_configs_without_user_supplied_ids(self):
        source_url = "https://team.feishu.cn/wiki/space/source-space"
        target_url = "https://team.feishu.cn/wiki/space/target-space"
        cli = FakeCli()

        config = build_config_from_links(source_url, target_url, cli)

        self.assertEqual(cli.calls, [])
        self.assertEqual(config.source, SourceConfig(
            "source-space", "space", source_url,
        ))
        self.assertEqual(config.target, TargetConfig(
            "target-space", None, "space",
        ))

    def test_rejects_source_and_target_that_resolve_to_same_resource(self):
        url = "https://team.feishu.cn/wiki/node-123"
        cli = FakeCli()
        with self.assertRaises(KnowledgeConfigBootstrapError) as caught:
            build_config_from_links(url, url, cli)
        self.assertEqual(caught.exception.status, "config_invalid")
        self.assertEqual(cli.calls, [])

    def test_rejects_identity_conflicting_node_response(self):
        cli = FakeCli({
            "source-node": node_payload("source-space", "source-node", "source-doc"),
            "target-node": node_payload("target-space", "different-node", "different-doc"),
        })
        with self.assertRaises(KnowledgeConfigBootstrapError) as caught:
            build_config_from_links(
                "https://team.feishu.cn/wiki/source-node",
                "https://team.feishu.cn/wiki/target-node",
                cli,
            )
        self.assertEqual(caught.exception.status, "config_invalid")
        self.assertIn("identity", str(caught.exception).lower())

    def test_build_strips_credential_shaped_query_parameters(self):
        source_url = "https://team.feishu.cn/wiki/source-node?from=share&access_token=shortsecret"
        target_url = "https://team.feishu.cn/wiki/target-node"
        cli = FakeCli({
            "source-node": node_payload("source-space", "source-node", "source-doc"),
            "target-node": node_payload("target-space", "target-node", "target-doc"),
        })
        config = build_config_from_links(source_url, target_url, cli)
        self.assertNotIn("shortsecret", config.source.wiki_url)
        self.assertNotIn("access_token", config.source.wiki_url)


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.destination = self.root / "config" / "feishu-knowledge-base.json"
        self.config = KnowledgeConfig(
            SourceConfig("source-space", "node", "https://team.feishu.cn/wiki/source"),
            TargetConfig("target-space", "target-node", "node"),
            "user",
            45,
            (Path("lark-cli"),),
        )

    def test_write_uses_same_directory_temp_file_then_atomic_replace(self):
        seen = {}
        real_replace = os.replace

        def recording_replace(source, destination):
            seen["source"] = Path(source)
            seen["destination"] = Path(destination)
            return real_replace(source, destination)

        with patch("knowledge_config_bootstrap.os.replace", side_effect=recording_replace):
            result = write_config_atomic(self.config, self.destination)

        self.assertEqual(result, self.destination)
        self.assertEqual(seen["destination"], self.destination)
        self.assertEqual(seen["source"].parent, self.destination.parent)
        self.assertNotEqual(seen["source"], self.destination)
        self.assertFalse(seen["source"].exists())
        payload = json.loads(self.destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)
        self.assertNotIn("cli_candidates", payload)
        self.assertNotIn("profile", payload)
        loaded = load_config(self.destination, self.root, {})
        self.assertEqual(loaded.source, self.config.source)
        self.assertEqual(loaded.target, self.config.target)

    def test_failed_replace_preserves_old_config_and_removes_temp_file(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_text('{"old": true}\n', encoding="utf-8")

        with patch("knowledge_config_bootstrap.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                write_config_atomic(self.config, self.destination)

        self.assertEqual(self.destination.read_text(encoding="utf-8"), '{"old": true}\n')
        self.assertEqual(list(self.destination.parent.glob("*.tmp")), [])
        self.assertEqual(list(self.destination.parent.glob(".*.tmp")), [])

    def test_serialized_config_contains_no_credential_fields(self):
        write_config_atomic(self.config, self.destination)
        serialized = self.destination.read_text(encoding="utf-8").lower()
        for forbidden in ("appsecret", "app_secret", "access_token", "refresh_token"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
