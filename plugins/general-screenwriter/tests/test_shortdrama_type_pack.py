import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
import stage_dag_codex
from creative_run_builder import CreativeRunRequest, build_creative_run
from quality_gate_contract import build_quality_gate_report
from screenwriter_context import CreativeContext
from shortdrama_checks import SHORTDRAMA_CHECK_IDS, validate_shortdrama_rules
from type_registry import (
    load_type_registry,
    resolve_type_pack,
    validate_type_contract,
)


CONTRACT = ROOT / "config" / "plugin-contract.json"


def config_pack():
    return resolve_type_pack(load_type_registry(), "shortdrama")


def active_pack():
    return replace(config_pack(), status="active")


def request(**overrides):
    values = dict(
        type_pack=active_pack(),
        context=CreativeContext("shortdrama", project_id="p1",
                                delivery_form="episode_script"),
        intent="creation", target="episode_script", run_id="sd-run-1",
        project_root=str(REPO_ROOT),
    )
    values.update(overrides)
    return CreativeRunRequest(**values)


def action(text):
    return {"kind": "action", "text": text}


def dialogue(speaker, text):
    return {"kind": "dialogue", "speaker": speaker, "text": text}


def scene(scene_id, location, time_of_day, lines, transition=""):
    return {
        "scene_id": scene_id,
        "heading": f"场{scene_id[1:]} {location} {time_of_day}",
        "location": location,
        "time_of_day": time_of_day,
        "lines": list(lines),
        "transition": transition,
    }


def scenes():
    return [
        scene("S1", "天台", "夜",
              [action("风把证物袋吹散。"), dialogue("林一", "谁动了我的证据？")],
              "切至走廊"),
        scene("S2", "走廊", "夜",
              [dialogue("林一", "监控少了一段。"), dialogue("陈默", "是人为删的。")],
              "切至会议室"),
        scene("S3", "会议室", "夜",
              [dialogue("陈默", "你替别人背了锅。"), dialogue("林一", "那就摊牌。")],
              "切至直播间"),
        scene("S4", "直播间", "夜",
              [dialogue("林一", "替身身份，今天我亲自揭。"), action("灯灭，屏幕亮起。")],
              "切回天台"),
        scene("S5", "天台", "夜",
              [dialogue("林一", "证据我拿到了。"), action("手机屏幕亮起：定位已共享。")],
              ""),
    ]


def beats():
    return [
        {"beat_id": "b1", "function": "hook", "scene_id": "S1"},
        {"beat_id": "b2", "function": "escalation", "scene_id": "S2"},
        {"beat_id": "b3", "function": "turn", "scene_id": "S3"},
        {"beat_id": "b4", "function": "closure", "scene_id": "S4"},
        {"beat_id": "b5", "function": "closing_hook", "scene_id": "S5"},
    ]


def characters():
    return [
        {"name": "林一", "states": [
            {"beat_id": "b1", "state": "calm"},
            {"beat_id": "b3", "state": "resolute"},
            {"beat_id": "b5", "state": "in_control"},
        ]},
        {"name": "陈默", "states": [{"beat_id": "b2", "state": "guarded"}]},
    ]


def episode(**overrides):
    payload = {
        "artifact_id": "episode_script",
        "format": "episode_script",
        "duration_seconds": 55,
        "scenes": scenes(),
        "beats": beats(),
        "conflict": {
            "goal": "夺回证据",
            "escalation_beat_ids": ["b2"],
            "closure_beat_id": "b4",
            "closed": True,
        },
        "characters": characters(),
    }
    payload.update(overrides)
    return payload


def episode_without_closing_hook():
    items = beats()
    items[-1] = {"beat_id": "b5", "function": "closure", "scene_id": "S5"}
    return episode(beats=items)


def context():
    return CreativeContext("shortdrama", project_id="p1",
                           delivery_form="episode_script")


class ConfigContractTests(unittest.TestCase):
    def test_config_shortdrama_is_active_with_full_contract(self):
        pack = config_pack()
        self.assertEqual(pack.status, "active")
        self.assertEqual(
            {item.artifact_id for item in pack.artifact_types},
            {"positioning", "episode_outline", "hook_sheet",
             "beat_sheet", "scene_table", "episode_script"},
        )
        self.assertEqual(
            {item.stage_id for item in pack.stages},
            {"session_init", "brief_gate", "knowledge_load", "episode_design",
             "hook_design", "beat_design", "scene_design",
             "episode_script_delegate", "hook_check", "pacing_check",
             "dialogue_check", "quality_gate", "confirmation_gate", "persistence"},
        )
        self.assertEqual(validate_type_contract(pack), pack)

    def test_config_pack_is_dispatchable(self):
        manifest = build_creative_run(request())
        self.assertEqual(stage_dag_codex.build_dispatch_plan(manifest)["status"], "ready")

    def test_contract_reports_shortdrama_active(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("shortdrama", contract["type_pack_contract"]["active_medium_ids"])


class CoreRunTests(unittest.TestCase):
    def test_shortdrama_core_run_is_built_from_type_pack(self):
        manifest = build_creative_run(request())
        self.assertEqual(manifest["artifact_type"], "episode_script")
        self.assertEqual(manifest["stages"][0]["stage_id"], "session_init")
        self.assertEqual(manifest["status"], "pending")
        self.assertEqual(
            manifest["resolution_snapshot"]["type_pack"]["medium_id"],
            "shortdrama",
        )
        confirmation = [item for item in manifest["stages"]
                        if item["stage_type"] == "confirmation"]
        self.assertEqual([item["stage_id"] for item in confirmation],
                         ["confirmation_gate"])

    def test_positioning_is_brief_input_not_run_target(self):
        with self.assertRaises(stage_dag.StageDagError):
            build_creative_run(request(target="positioning"))

    def test_planned_pack_is_rejected_before_manifest_construction(self):
        with self.assertRaises(Exception):
            build_creative_run(
                request(type_pack=replace(config_pack(), status="planned"))
            )


class ContentCheckTests(unittest.TestCase):
    def test_all_eight_checks_are_declared(self):
        self.assertEqual(
            set(SHORTDRAMA_CHECK_IDS),
            {"opening_hook", "turning_point", "closing_hook", "pacing_density",
             "conflict_closure", "character_state", "format", "duration"},
        )

    def test_well_formed_episode_passes_every_check(self):
        for check_id in SHORTDRAMA_CHECK_IDS:
            with self.subTest(check_id=check_id):
                result = validate_shortdrama_rules(check_id, episode(), context())
                self.assertEqual(result.status, "pass")
                self.assertEqual(result.evidence["source"], "content")

    def test_hollow_script_content_fails_even_with_all_fields(self):
        items = scenes()
        items[0]["lines"] = [action("走。"), action("站住。")]
        result = validate_shortdrama_rules(
            "opening_hook", episode(scenes=items), context())
        self.assertEqual(result.status, "fail")

    def test_turn_must_sit_in_middle_band(self):
        items = beats()
        turn = items.pop(2)
        items.append(turn)
        result = validate_shortdrama_rules(
            "turning_point", episode(beats=items), context())
        self.assertEqual(result.status, "fail")

    def test_duration_mismatch_with_content_is_reported(self):
        result = validate_shortdrama_rules(
            "duration", episode(duration_seconds=600), context())
        self.assertEqual(result.status, "fail")
        self.assertIn("estimated_seconds", result.evidence)

    def test_unregistered_speaker_fails_character_state(self):
        items = scenes()
        items[1]["lines"].append(dialogue("神秘人", "东西在我这。"))
        result = validate_shortdrama_rules(
            "character_state", episode(scenes=items), context())
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["unknown_speakers"], ["神秘人"])

    def test_parse_failure_returns_fail_with_errors(self):
        result = validate_shortdrama_rules(
            "format", episode(scenes=[]), context())
        self.assertEqual(result.status, "fail")
        self.assertTrue(result.evidence["errors"])

    def test_missing_closing_hook_fails_user_confirmation_risk(self):
        result = validate_shortdrama_rules(
            "closing_hook", episode_without_closing_hook(), context())
        self.assertEqual(result.status, "fail")
        rule = next(rule for rule in config_pack().quality_rules
                    if rule.check_id == "closing_hook")
        self.assertEqual(rule.blocking_policy, "require_user_confirmation")
        report = build_quality_gate_report(
            [rule],
            [result],
            gate_id="shortdrama-quality",
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.confirmation_ready)

    def test_each_check_fails_on_broken_content(self):
        cases = {
            "opening_hook": {"beats": []},
            "turning_point": {
                "beats": [item for item in beats()
                          if item["function"] != "turn"]
            },
            "closing_hook": {"beats": beats()[:-1]},
            "pacing_density": {"duration_seconds": None},
            "conflict_closure": {
                "conflict": {"goal": "夺回证据", "escalation_beat_ids": ["b2"],
                             "closure_beat_id": "b4", "closed": False}
            },
            "character_state": {"characters": []},
            "format": {"format": "screenplay"},
            "duration": {"duration_seconds": 0},
        }
        for check_id, overrides in cases.items():
            with self.subTest(check_id=check_id):
                result = validate_shortdrama_rules(
                    check_id, episode(**overrides), context())
                self.assertEqual(result.status, "fail")

    def test_unknown_check_id_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_shortdrama_rules("nonexistent", episode(), context())


if __name__ == "__main__":
    unittest.main(verbosity=2)
