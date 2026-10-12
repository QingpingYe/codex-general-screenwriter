import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "general-screenwriter"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import user_skill_gate


def _valid_manifest(skill_id):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "title": "Probe Skill",
        "description": "probe",
        "user_name": "tester",
        "skill_type": "prompt_skill",
        "supports": {
            "medium_ids": ["shortdrama"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        },
        "content": "SKILL.md",
        "updated_at": "2026-10-10T00:00:00+08:00",
    }


class UserSkillGateTests(unittest.TestCase):
    def test_real_plugin_skill_trees_pass(self):
        self.assertEqual(user_skill_gate.check_plugin_skill_trees(PLUGIN_ROOT), ())

    def test_loose_file_fails_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin_root = Path(temp) / "plugin-root"
            (plugin_root / "config").mkdir(parents=True)
            shutil.copy2(
                PLUGIN_ROOT / "config" / "type-packs.json",
                plugin_root / "config" / "type-packs.json",
            )
            pack = plugin_root / "skills" / "user-skills" / "probe-skill"
            pack.mkdir(parents=True)
            (pack / "manifest.json").write_text(
                json.dumps(_valid_manifest("probe-skill"), ensure_ascii=False),
                encoding="utf-8",
            )
            (pack / "SKILL.md").write_text("Use this.", encoding="utf-8")
            (plugin_root / "skills" / "user-skills" / "stray.exe").write_bytes(b"MZ")

            errors = user_skill_gate.check_plugin_skill_trees(plugin_root)

            self.assertTrue(errors)
            self.assertIn("stray.exe", errors[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
