import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from screenwriter_context import (
    ContextError,
    CreativeContext,
    context_from_dict,
    context_to_dict,
    validate_context,
)


class ScreenwriterContextTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_genres(self):
        context = context_from_dict({
            "medium_id": "picture-book",
            "genre_ids": ["mystery", "comedy", "mystery"],
        })
        self.assertEqual(context.medium_id, "picturebook")
        self.assertEqual(context.genre_ids, ("mystery", "comedy"))

    def test_rejects_unknown_medium_and_blank_genre(self):
        with self.assertRaises(ContextError):
            context_from_dict({"medium_id": "unknown"})
        with self.assertRaises(ContextError):
            context_from_dict({"medium_id": "shortdrama", "genre_ids": [""]})
        with self.assertRaises(ContextError):
            context_from_dict({"medium_id": "film"})

    def test_legacy_context_can_omit_project_id(self):
        context = context_from_dict({"medium_id": "picturebook"})
        self.assertIsNone(context.project_id)

    def test_context_round_trip_preserves_unit_scope(self):
        context = context_from_dict({
            "medium_id": "shortdrama",
            "genre_ids": ["mystery"],
            "series_id": "north-star",
            "project_id": "feature-one",
            "season_id": "season-1",
            "episode_id": "episode-2",
            "scene_id": "scene-7",
            "delivery_form": "episode_script",
        })
        self.assertEqual(context_from_dict(context_to_dict(context)), context)

    def test_new_context_can_require_project_id(self):
        with self.assertRaises(ContextError):
            validate_context(CreativeContext("shortdrama"), require_project=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
