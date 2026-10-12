import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_skill_index import build_index, render_index
from governance_check import check_repo


TEST_VERSION = "1.2.3"


def write_plugin(root):
    plugin = root / "plugins" / "general-screenwriter"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "config").mkdir()
    skill = plugin / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# demo", encoding="utf-8")
    (skill / "skill-meta.json").write_text(
        json.dumps({
            "schema_version": 1,
            "skill_id": "demo-skill",
            "visibility": "system",
            "supports": {
                "medium_ids": ["picturebook"],
                "genre_ids": ["all"],
                "series_ids": ["all"],
                "project_ids": ["all"],
                "stage_ids": ["all"],
                "artifact_ids": ["all"],
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"version": TEST_VERSION}), encoding="utf-8"
    )
    (plugin / "config" / "plugin-contract.json").write_text(
        json.dumps({
            "schema_version": 1,
            "entry_skill": "demo-skill",
            "skills": ["demo-skill"],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (plugin / "config" / "skill-index.json").write_text(
        render_index(build_index(plugin)), encoding="utf-8"
    )
    return plugin


class GovernanceSkillIndexTests(unittest.TestCase):
    def test_fresh_index_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            write_plugin(Path(temp))
            report = check_repo(Path(temp))
            self.assertEqual(report.errors, ())
            self.assertTrue(report.ok)

    def test_stale_index_is_error(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin = write_plugin(Path(temp))
            (plugin / "config" / "skill-index.json").write_text(
                '{"schema_version": 1, "entries": []}\n', encoding="utf-8"
            )
            report = check_repo(Path(temp))
            self.assertFalse(report.ok)
            self.assertTrue(
                any("stale" in error for error in report.errors)
            )

    def test_missing_index_is_error_when_entries_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin = write_plugin(Path(temp))
            (plugin / "config" / "skill-index.json").unlink()
            report = check_repo(Path(temp))
            self.assertFalse(report.ok)
            self.assertTrue(
                any("missing" in error for error in report.errors)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
