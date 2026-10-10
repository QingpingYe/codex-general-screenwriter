import json
import os
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
CONTRACT = ROOT / "config" / "plugin-contract.json"
PLUGIN_README = ROOT / "README.md"
REPO_README = ROOT.parent.parent / "README.md"
sys.path.insert(0, str(ROOT / "skills" / "feishu-knowledge-store" / "scripts"))
from shared_schema import PAGE_TYPES

EXPECTED_RELEASE_VERSION = os.environ.get(
    "GENERAL_SCREENWRITER_EXPECTED_VERSION", "",
).strip().removeprefix("v")


class ReleaseSurfaceTests(unittest.TestCase):
    def test_plugin_identity_is_general_screenwriter(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        marketplace = json.loads(
            (ROOT.parent.parent / ".agents" / "plugins" / "marketplace.json")
            .read_text(encoding="utf-8")
        )
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        repo_text = REPO_README.read_text(encoding="utf-8")

        self.assertEqual(ROOT.name, "general-screenwriter")
        self.assertEqual(manifest["name"], "general-screenwriter")
        self.assertEqual(marketplace["name"], "general-screenwriter-github")
        self.assertEqual(marketplace["plugins"][0]["name"], "general-screenwriter")
        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            "./plugins/general-screenwriter",
        )
        self.assertEqual(contract["entry_skill"], "general-screenwriter")
        self.assertEqual(
            contract["compatibility"]["legacy_entry_skill"],
            "picturebook-screenwriter",
        )
        self.assertIn(
            "codex plugin add general-screenwriter@general-screenwriter-github",
            repo_text,
        )

    def test_manifest_describes_completed_art_phase(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        self.assertIn("gated illustration workflow", manifest["description"])
        self.assertIn(
            "为已批准的绘本脚本生成结构化插画提示词",
            manifest["interface"]["defaultPrompt"],
        )
        self.assertIn("HTML 预览", manifest["interface"]["longDescription"])

    def test_contract_declares_phase5_artifacts(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

        for artifact in (
            "illustration_prompt_payload",
            "image_asset",
            "asset_registry",
            "html_preview",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, contract["artifact_types"])

    def test_plugin_readme_no_longer_marks_art_as_unsupported(self):
        text = PLUGIN_README.read_text(encoding="utf-8")

        self.assertIn("image-generate", text)
        self.assertIn("illustration-export", text)
        self.assertNotIn("- 插画与素材图生成\n", text)
        self.assertNotIn("- HTML 预览导出\n", text)

    def test_repo_readme_describes_self_contained_preview(self):
        text = REPO_README.read_text(encoding="utf-8")

        self.assertIn("Gated illustration workflow", text)
        self.assertIn("Self-contained HTML preview", text)


class ReleaseVersionTests(unittest.TestCase):
    def test_manifest_version_is_semver(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIsNotNone(re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]))

    @unittest.skipUnless(
        EXPECTED_RELEASE_VERSION,
        "set GENERAL_SCREENWRITER_EXPECTED_VERSION for release verification",
    )
    def test_release_version_matches_expected(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], EXPECTED_RELEASE_VERSION)

    def test_changelog_records_phase5(self):
        text = (ROOT.parent.parent / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]", text)
        self.assertIn("Gated illustration workflow", text)
        self.assertIn("Self-contained HTML preview", text)


class ReleaseChecklistTests(unittest.TestCase):
    def test_release_checklist_names_all_gates(self):
        text = (ROOT.parent.parent / "docs" / "RELEASE.md").read_text(encoding="utf-8")
        for gate in (
            "run_plugin_tests.py",
            "validate_plugin.py",
            "GENERAL_SCREENWRITER_EXPECTED_VERSION",
            "live Feishu",
            "marketplace",
        ):
            with self.subTest(gate=gate):
                self.assertIn(gate, text)

    def test_readme_documents_aggregate_verification(self):
        text = (ROOT.parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("python .\\scripts\\run_plugin_tests.py", text)

    def test_release_checklist_uses_valid_validator_path(self):
        text = (ROOT.parent.parent / "docs" / "RELEASE.md").read_text(encoding="utf-8")
        self.assertNotIn("<codex-home>", text)
        self.assertIn("$env:CODEX_HOME", text)
        self.assertIn(r'"$codexHome\skills\.system', text)

    def test_readme_documents_workspace_config_discovery(self):
        text = REPO_README.read_text(encoding="utf-8")
        for value in (
            "feishu-knowledge-base.json",
            "GENERAL_SCREENWRITER_KB_CONFIG",
            "authority_cli.py",
            "config-status",
            "非权威",
        ):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_loader_skill_documents_explicit_offline_opt_in(self):
        text = (ROOT / "skills" / "knowledge-loader" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("authority_cli.py", text)
        self.assertIn("--allow-offline-cache", text)
        self.assertIn("非权威", text)

    def test_readme_documents_portable_config_discovery(self):
        text = REPO_README.read_text(encoding="utf-8")
        for value in (
            "ancestor",
            "%APPDATA%\\general-screenwriter",
            "${XDG_CONFIG_HOME:-~/.config}/general-screenwriter",
            "GENERAL_SCREENWRITER_KB_CONFIG",
            "deprecated",
        ):
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_readme_has_no_author_machine_paths(self):
        for path in (REPO_README, PLUGIN_README):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("E:\\海外绘本", text)
                self.assertNotIn("C:\\Users\\lvan", text)

    def test_plugin_readme_links_to_canonical_operator_guide(self):
        plugin_text = PLUGIN_README.read_text(encoding="utf-8")
        repo_text = REPO_README.read_text(encoding="utf-8")
        base_url = "https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md"
        headings = re.findall(r"^## (.+)$", repo_text, re.MULTILINE)
        anchors = {heading.lower().replace(" ", "-") for heading in headings}
        for anchor in (
            "add-the-plugin", "use-the-plugin", "feishu-knowledge-setup",
            "configuration-discovery", "feishu-runtime-commands", "verify-locally",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(f"{base_url}#{anchor}", plugin_text)
                self.assertIn(anchor, anchors)
        self.assertNotIn("```", plugin_text, "operator examples belong in the root README")

    def test_documented_authority_page_types_match_runtime_schema(self):
        text = REPO_README.read_text(encoding="utf-8")
        examples = re.findall(r"--page-types\s+([A-Za-z0-9,-]+)", text)
        self.assertTrue(examples, "root README must include an authority query example")
        for example in examples:
            with self.subTest(example=example):
                self.assertLessEqual(set(example.split(",")), PAGE_TYPES)
        self.assertIn("`source.wiki_url`", text)


class LiveAcceptanceTests(unittest.TestCase):
    def test_live_acceptance_names_required_evidence(self):
        path = (
            ROOT.parent.parent
            / "docs"
            / "superpowers"
            / "plans"
            / "2026-09-18-06-live-acceptance.md"
        )
        text = path.read_text(encoding="utf-8")
        for evidence in (
            "User A",
            "User B",
            "revision_id",
            "human edit survives",
            "only one lease",
            "explicit user approval",
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, text)


if __name__ == "__main__":
    unittest.main()
