"""Dual-harness (Codex + Claude Code) packaging contract tests.

The plugin ships one shared ``skills/`` tree with per-host manifests:

- Codex reads ``.codex-plugin/plugin.json`` together with
  ``.agents/plugins/marketplace.json``.
- Claude Code reads ``.claude-plugin/plugin.json`` together with the
  repository-root ``.claude-plugin/marketplace.json``.

Both hosts must see the same plugin name and version, and the shared skill
bodies must stay harness-neutral: neither Codex ``$skill`` syntax nor Claude
``/plugin:skill`` syntax may appear inside ``skills/``.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
CODEX_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
CLAUDE_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
RELEASE_DOC = REPO_ROOT / "docs" / "RELEASE.md"
ENFORCEMENT_DOC = REPO_ROOT / "docs" / "ENFORCEMENT.md"
REPO_README = REPO_ROOT / "README.md"

KEBAB_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_PLUGIN_PREFIXES = ("claude-", "anthropic-", "cc-plugin-")
RESERVED_MARKETPLACE_NAMES = {"inline", "skills-dir", "synced"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# Codex trigger syntax ($skill-name) must not leak into shared skill bodies.
DOLLAR_SKILL_SYNTAX = re.compile(r"(?<![\w$])\$[a-z][a-z0-9-]*")
# Claude Code slash-command syntax (/plugin:skill) must not either; URLs and
# scoped identifiers such as docx:document:create are unaffected.
SLASH_SKILL_SYNTAX = re.compile(r"(?<![\w:/])/[a-z][a-z0-9-]*:[a-z][a-z0-9-]*")

EXPECTED_MARKETPLACE_NAME = "general-screenwriter-git"
EXPECTED_SOURCE = "./plugins/general-screenwriter"


class _ManifestTestCase(unittest.TestCase):
    def load_json(self, path):
        self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO_ROOT)}")
        return json.loads(path.read_text(encoding="utf-8"))


class ClaudeManifestTests(_ManifestTestCase):
    def test_claude_plugin_manifest_matches_the_shared_identity(self):
        manifest = self.load_json(CLAUDE_MANIFEST)
        codex = self.load_json(CODEX_MANIFEST)

        self.assertEqual(manifest["name"], "general-screenwriter")
        self.assertTrue(KEBAB_CASE.match(manifest["name"]))
        for prefix in RESERVED_PLUGIN_PREFIXES:
            self.assertFalse(manifest["name"].startswith(prefix))
        self.assertTrue(SEMVER.match(manifest["version"]))
        self.assertEqual(manifest["version"], codex["version"])
        self.assertTrue(manifest["description"].strip())
        self.assertTrue(manifest["author"]["name"])
        self.assertEqual(manifest["author"]["name"], codex["author"]["name"])

    def test_claude_marketplace_entry_binds_the_plugin(self):
        marketplace = self.load_json(CLAUDE_MARKETPLACE)
        manifest = self.load_json(CLAUDE_MANIFEST)

        self.assertEqual(marketplace["name"], EXPECTED_MARKETPLACE_NAME)
        self.assertNotIn(marketplace["name"], RESERVED_MARKETPLACE_NAMES)
        self.assertTrue(marketplace["owner"]["name"])

        entries = [
            entry for entry in marketplace["plugins"]
            if entry["name"] == manifest["name"]
        ]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["source"], EXPECTED_SOURCE)
        self.assertEqual(entry["version"], manifest["version"])

    def test_every_manifest_version_source_stays_in_sync(self):
        codex = self.load_json(CODEX_MANIFEST)
        claude = self.load_json(CLAUDE_MANIFEST)
        marketplace = self.load_json(CLAUDE_MARKETPLACE)
        entry = [
            item for item in marketplace["plugins"]
            if item["name"] == claude["name"]
        ][0]
        changelog = CHANGELOG.read_text(encoding="utf-8")
        released = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE)

        self.assertTrue(released, "changelog must record a released version")
        versions = {codex["version"], claude["version"], entry["version"], released[0]}
        self.assertEqual(len(versions), 1, f"version drift across manifests: {versions}")

    def test_repo_readme_documents_the_claude_code_install_path(self):
        text = REPO_README.read_text(encoding="utf-8")

        self.assertIn("Claude Code", text)
        self.assertIn(
            "/plugin marketplace add QingpingYe/lvan-general-screenwriter", text
        )
        self.assertIn("general-screenwriter@general-screenwriter-git", text)


class SharedSkillNeutralityTests(unittest.TestCase):
    def test_skill_bodies_avoid_harness_specific_invocation_syntax(self):
        documents = sorted((ROOT / "skills").rglob("*.md"))
        self.assertTrue(documents)
        for path in documents:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertIsNone(
                    DOLLAR_SKILL_SYNTAX.search(text),
                    "Codex $skill invocation syntax found in a shared skill body",
                )
                self.assertIsNone(
                    SLASH_SKILL_SYNTAX.search(text),
                    "Claude /plugin:skill invocation syntax found in a shared skill body",
                )

    def test_user_skill_hub_exposes_frontmatter_for_both_hosts(self):
        text = (ROOT / "skills" / "user-skill-hub" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertTrue(text.startswith("---\n"), "SKILL.md must start with frontmatter")
        self.assertIn("name: user-skill-hub", text)
        self.assertIn("description:", text)


class DualHarnessGovernanceTests(_ManifestTestCase):
    def test_release_docs_include_the_claude_code_validation_step(self):
        text = RELEASE_DOC.read_text(encoding="utf-8")

        self.assertIn("Claude Code", text)
        self.assertIn("claude plugin validate", text)
        self.assertIn(".claude-plugin", text)

    def test_enforcement_doc_maps_the_dual_harness_packaging_level(self):
        text = ENFORCEMENT_DOC.read_text(encoding="utf-8")

        self.assertIn(".claude-plugin", text)
        self.assertIn("Claude Code", text)

    def test_release_gate_runs_the_dual_harness_contract_first(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import release_gate

        names = [name for name, _ in release_gate.GATE_STEPS]
        steps = dict(release_gate.GATE_STEPS)

        self.assertIn("dual_harness_contract", names)
        self.assertIn("test_dual_harness_contract.py", steps["dual_harness_contract"])
        self.assertLess(
            names.index("dual_harness_contract"), names.index("offline_regression")
        )

    def test_package_check_requires_both_host_manifests(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from package_check import build_package_report

        report = build_package_report(REPO_ROOT)

        self.assertTrue(report.ok, report.errors)
        self.assertIn(".claude-plugin/plugin.json", report.files)


if __name__ == "__main__":
    unittest.main()
