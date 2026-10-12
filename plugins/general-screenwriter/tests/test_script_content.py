import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from script_content import (
    ScriptContentError,
    parse_episode_script,
    scene_dialogue_lines,
)


def line(kind, text, speaker=None):
    payload = {"kind": kind, "text": text}
    if speaker is not None:
        payload["speaker"] = speaker
    return payload


def scene(scene_id="S1", lines=None, transition="切至走廊", **overrides):
    payload = {
        "scene_id": scene_id,
        "heading": f"场 {scene_id} 天台 夜",
        "location": "天台",
        "time_of_day": "夜",
        "lines": lines if lines is not None else [
            line("action", "风把证物袋吹散。"),
            line("dialogue", "谁动了我的证据？", "林一"),
        ],
        "transition": transition,
    }
    payload.update(overrides)
    return payload


def script(**overrides):
    payload = {
        "artifact_id": "episode_script",
        "format": "episode_script",
        "duration_seconds": 55,
        "scenes": [scene("S1"), scene("S2", transition="")],
        "beats": [
            {"beat_id": "b1", "function": "hook", "scene_id": "S1"},
            {"beat_id": "b2", "function": "closing_hook", "scene_id": "S2"},
        ],
        "conflict": {
            "goal": "夺回证据",
            "escalation_beat_ids": [],
            "closure_beat_id": "b2",
            "closed": True,
        },
        "characters": [
            {"name": "林一", "states": [{"beat_id": "b1", "state": "calm"}]}
        ],
    }
    payload.update(overrides)
    return payload


class ParseEpisodeScriptTests(unittest.TestCase):
    def test_valid_payload_parses_scenes_lines_and_speakers(self):
        parsed = parse_episode_script(script())
        self.assertEqual([item.scene_id for item in parsed.scenes], ["S1", "S2"])
        self.assertEqual(parsed.scene_index["S2"], 1)
        self.assertEqual(parsed.line_count, 4)
        self.assertEqual(parsed.dialogue_count, 2)
        self.assertEqual(parsed.action_count, 2)
        self.assertEqual(parsed.speakers, frozenset({"林一"}))
        self.assertEqual(
            [item.text for item in scene_dialogue_lines(parsed, "S1")],
            ["谁动了我的证据？"],
        )

    def test_duplicate_scene_id_is_rejected(self):
        with self.assertRaises(ScriptContentError) as caught:
            parse_episode_script(
                script(scenes=[scene("S1"), scene("S1", transition="")])
            )
        self.assertTrue(any("重复" in item for item in caught.exception.errors))

    def test_unknown_line_kind_is_rejected(self):
        broken = scene("S1", lines=[line("voiceover", "旁白内容", "林一")])
        with self.assertRaises(ScriptContentError) as caught:
            parse_episode_script(script(scenes=[broken]))
        self.assertTrue(any("kind" in item for item in caught.exception.errors))

    def test_dialogue_without_speaker_is_rejected(self):
        broken = scene("S1", lines=[line("dialogue", "谁动了我的证据？")])
        with self.assertRaises(ScriptContentError) as caught:
            parse_episode_script(script(scenes=[broken]))
        self.assertTrue(any("speaker" in item for item in caught.exception.errors))

    def test_empty_lines_are_rejected(self):
        broken = scene("S1", lines=[])
        with self.assertRaises(ScriptContentError):
            parse_episode_script(script(scenes=[broken]))

    def test_beat_with_unknown_scene_reference_is_rejected(self):
        beats = [{"beat_id": "b1", "function": "hook", "scene_id": "S9"}]
        with self.assertRaises(ScriptContentError) as caught:
            parse_episode_script(script(beats=beats))
        self.assertTrue(any("scene" in item for item in caught.exception.errors))

    def test_non_mapping_payload_is_rejected(self):
        with self.assertRaises(ScriptContentError):
            parse_episode_script(["not", "a", "mapping"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
