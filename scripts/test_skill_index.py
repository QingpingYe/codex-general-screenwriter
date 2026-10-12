import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "general-screenwriter"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_skill_index


def system_meta(skill_id):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "visibility": "system",
        "supports": {
            "medium_ids": ["picturebook"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        },
    }


class SkillIndexTests(unittest.TestCase):
    def test_committed_index_matches_rebuild(self):
        committed = (
            PLUGIN_ROOT / "config" / "skill-index.json"
        ).read_text(encoding="utf-8")
        rebuilt = build_skill_index.render_index(
            build_skill_index.build_index(PLUGIN_ROOT)
        )
        self.assertEqual(committed, rebuilt)

    def test_index_covers_system_and_user_layers(self):
        index = build_skill_index.build_index(PLUGIN_ROOT)
        by_id = {entry["skill_id"]: entry for entry in index["entries"]}
        self.assertEqual(by_id["general-screenwriter"]["layer"], "system")
        self.assertEqual(
            by_id["novel-to-shortdrama-adaptation"]["layer"], "user"
        )
        self.assertEqual(
            by_id["text-craft"]["supports"]["medium_ids"], ["picturebook"]
        )

    def test_rebuild_is_deterministic_and_tracks_new_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "plugin-root"
            directory = root / "skills" / "demo-skill"
            directory.mkdir(parents=True)
            (directory / "skill-meta.json").write_text(
                json.dumps(system_meta("demo-skill")), encoding="utf-8"
            )

            first = build_skill_index.render_index(
                build_skill_index.build_index(root)
            )
            second = build_skill_index.render_index(
                build_skill_index.build_index(root)
            )

            self.assertEqual(first, second)
            self.assertIn('"skill_id": "demo-skill"', first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
