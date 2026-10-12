import copy
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
from screenwriter_context import CreativeContext
from tv_longform_checks import TV_LONGFORM_CHECK_IDS, validate_tv_longform_rules
from type_registry import load_type_registry, resolve_type_pack, validate_type_contract


def config_pack():
    return resolve_type_pack(load_type_registry(), "tv_longform")


def active_pack():
    return replace(config_pack(), status="active")


def request(**overrides):
    values = dict(
        type_pack=active_pack(),
        context=CreativeContext(
            "tv_longform", project_id="p1", series_id="s1",
            season_id="season-1", delivery_form="season_episode_script"),
        intent="creation", target="episode_script", run_id="tv-run-1",
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
              [dialogue("林一", "内鬼就在我们中间。"), dialogue("陈默", "先别下结论。")],
              "切至走廊"),
        scene("S2", "走廊", "夜",
              [dialogue("林一", "怀表指向密室。"), action("灯闪了两下。")],
              "切回天台"),
        scene("S3", "天台", "夜",
              [dialogue("陈默", "你在怀疑我？"), dialogue("林一", "我只信证据。")],
              "切至会议室"),
        scene("S4", "会议室", "夜",
              [dialogue("林一", "明早对质。"), action("窗外天色泛白。")],
              ""),
    ]


def episode(**overrides):
    payload = {
        "artifact_id": "episode_script",
        "format": "episode_script",
        "series_id": "s1",
        "season_id": "season-1",
        "episode_id": "e2",
        "episode_function": "推进主线：揭露内鬼线索。",
        "arc_beat_ref": "arc-b2",
        "scenes": scenes(),
        "timeline": [
            {"order": 11, "event": "夜谈", "scene_id": "S1"},
            {"order": 12, "event": "对峙", "scene_id": "S2"},
        ],
        "foreshadows": [
            {"id": "f2", "source": "旧怀表", "purpose": "指向密室",
             "scene_id": "S1", "planned_payoff": "本季末揭晓"},
        ],
        "payoffs": [
            {"foreshadow_id": "f1", "resolution": "怀表指向密室", "scene_id": "S2"},
        ],
        "character_states": [
            {"name": "林一", "prior_state": "calm", "state": "shaken",
             "transition_scene_id": "S2"},
            {"name": "陈默", "prior_state": "guarded", "state": "guarded",
             "transition_scene_id": "S1"},
        ],
        "continuity_ledger_ref": "series/s1/continuity/e2",
    }
    payload.update(overrides)
    return payload


def longform_references(**overrides):
    payload = {
        "season_arc": {
            "artifact_id": "season_arc",
            "beats": [
                {"beat_id": "arc-b1", "goal": "铺垫内鬼疑云"},
                {"beat_id": "arc-b2", "goal": "揭露内鬼线索"},
            ],
        },
        "series_bible": {
            "artifact_id": "series_bible",
            "series_id": "s1",
            "characters": [{"name": "林一"}, {"name": "陈默"}],
            "banned_terms": ["穿越"],
        },
        "character_arc_map": {
            "artifact_id": "character_arc_map",
            "latest": {
                "episode_id": "e1",
                "states": [
                    {"name": "林一", "state": "calm"},
                    {"name": "陈默", "state": "guarded"},
                ],
            },
        },
        "timeline_ledger": {"artifact_id": "timeline_ledger", "last_order": 10},
        "episode_list": {
            "artifact_id": "episode_list",
            "episodes": {"e2": {"function": "推进主线：揭露内鬼线索。"}},
        },
        "continuity_ledger": {
            "artifact_id": "continuity_ledger",
            "linked_artifacts": [
                "episode_script", "season_arc", "character_arc_map",
            ],
            "entries": [
                {"field": "character_states", "value": "林一: calm -> shaken"},
                {"field": "timeline", "value": "order 11-12"},
            ],
            "conflicts": [],
            "open_foreshadows": [
                {"id": "f1", "source": "门缝里的信", "purpose": "指向内鬼"},
            ],
        },
    }
    for key, value in overrides.items():
        if key == "timeline_last_order":
            payload["timeline_ledger"] = dict(payload["timeline_ledger"])
            payload["timeline_ledger"]["last_order"] = value
        elif key == "prior_states":
            payload["character_arc_map"] = copy.deepcopy(payload["character_arc_map"])
            states = [
                {"name": name, "state": state} for name, state in value.items()
            ]
            payload["character_arc_map"]["latest"]["states"] = states
        else:
            payload[key] = value
    return payload


def context():
    return CreativeContext("tv_longform", project_id="p1", series_id="s1",
                           season_id="season-1")


class ConfigContractTests(unittest.TestCase):
    def test_config_tv_longform_is_active_with_full_contract(self):
        pack = config_pack()
        self.assertEqual(pack.status, "active")
        self.assertEqual(
            {item.artifact_id for item in pack.artifact_types},
            {"series_bible", "character_arc_map", "timeline_ledger", "season_arc",
             "episode_list", "episode_outline", "scene_table", "episode_script",
             "continuity_ledger"},
        )
        self.assertEqual(
            {item.stage_id for item in pack.stages},
            {"session_init", "brief_gate", "series_load", "season_design",
             "episode_design", "scene_design", "episode_script_delegate",
             "continuity_check", "foreshadow_check", "character_state_check",
             "quality_gate", "confirmation_gate", "persistence"},
        )
        self.assertEqual(validate_type_contract(pack), pack)

    def test_config_pack_is_dispatchable(self):
        manifest = build_creative_run(request())
        self.assertEqual(stage_dag_codex.build_dispatch_plan(manifest)["status"], "ready")


class CoreRunTests(unittest.TestCase):
    def test_tv_longform_core_run_is_built_from_type_pack(self):
        manifest = build_creative_run(request())
        self.assertEqual(manifest["artifact_type"], "episode_script")
        self.assertEqual(manifest["stages"][0]["stage_id"], "session_init")
        self.assertEqual(manifest["resolution_snapshot"]["type_pack"]["medium_id"], "tv_longform")
        self.assertEqual(
            [item["stage_id"] for item in manifest["stages"]
             if item["stage_type"] == "confirmation"],
            ["confirmation_gate"],
        )

    def test_revision_with_series_context_builds_from_pack(self):
        manifest = build_creative_run(request(
            intent="revision", run_id="tv-run-2", root_run_id="tv-run-1",
            revision_of_run_id="tv-run-1", revision_iteration=2,
            revision_feedback=[{"issue": "continuity", "instruction": "fix"}],
            source_artifact_ref="series/s1/episode_script_v1.md",
        ))
        self.assertEqual(manifest["intent"], "revision")
        self.assertEqual(manifest["revision_of_run_id"], "tv-run-1")


class ContentCheckTests(unittest.TestCase):
    def test_all_nine_checks_are_declared(self):
        self.assertEqual(
            set(TV_LONGFORM_CHECK_IDS),
            {"season_arc", "episode_function", "character_state", "timeline",
             "foreshadow", "payoff", "scene_transition", "series_constraint",
             "continuity"},
        )

    def test_well_formed_episode_passes_every_check_with_references(self):
        for check_id in TV_LONGFORM_CHECK_IDS:
            with self.subTest(check_id=check_id):
                result = validate_tv_longform_rules(
                    check_id, episode(), context(), longform_references())
                self.assertEqual(result.status, "pass", result.message)
                self.assertEqual(result.evidence["source"], "content")

    def test_missing_series_bible_fails_closed(self):
        result = validate_tv_longform_rules("series_constraint", episode(), context())
        self.assertEqual(result.status, "fail")

    def test_missing_prior_states_fails_closed(self):
        result = validate_tv_longform_rules("character_state", episode(), context())
        self.assertEqual(result.status, "fail")

    def test_timeline_regression_against_previous_ledger_is_reported(self):
        references = longform_references(timeline_last_order=11)
        result = validate_tv_longform_rules("timeline", episode(), context(), references)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["regressions"], ["e2:order-11"])

    def test_prior_state_mismatch_reports_character_conflict(self):
        references = longform_references(prior_states={"林一": "asleep", "陈默": "guarded"})
        result = validate_tv_longform_rules("character_state", episode(), context(), references)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["conflicts"], ["s1:e2:character-state"])

    def test_unregistered_speaker_fails_series_constraint(self):
        items = scenes()
        items[2]["lines"].append(dialogue("神秘人", "别查了。"))
        result = validate_tv_longform_rules(
            "series_constraint", episode(scenes=items), context(), longform_references())
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["unknown_speakers"], ["神秘人"])

    def test_banned_term_hit_fails_series_constraint(self):
        items = scenes()
        items[0]["lines"].append(dialogue("陈默", "除非她穿越回来。"))
        result = validate_tv_longform_rules(
            "series_constraint", episode(scenes=items), context(), longform_references())
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["banned_hits"], ["穿越"])

    def test_scene_transition_gap_is_reported(self):
        items = scenes()
        items[0]["transition"] = ""
        result = validate_tv_longform_rules(
            "scene_transition", episode(scenes=items), context(), longform_references())
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["violations"], ["S1->S2"])

    def test_parse_failure_returns_fail_with_errors(self):
        result = validate_tv_longform_rules(
            "continuity", episode(scenes=[]), context(), longform_references())
        self.assertEqual(result.status, "fail")
        self.assertTrue(result.evidence["errors"])

    def test_each_check_fails_on_broken_content(self):
        cases = {
            "season_arc": {"arc_beat_ref": "arc-missing"},
            "episode_function": {"episode_function": ""},
            "timeline": {"timeline": []},
            "foreshadow": {"foreshadows": []},
            "payoff": {"payoffs": []},
            "scene_transition": None,
            "character_state": {"character_states": []},
            "series_constraint": {"series_id": ""},
            "continuity": {"continuity_ledger_ref": ""},
        }
        for check_id, overrides in cases.items():
            with self.subTest(check_id=check_id):
                if check_id == "scene_transition":
                    items = scenes()
                    items[0]["transition"] = ""
                    artifact = episode(scenes=items)
                else:
                    artifact = episode(**overrides)
                result = validate_tv_longform_rules(
                    check_id, artifact, context(), longform_references())
                self.assertEqual(result.status, "fail")

    def test_unknown_check_id_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_tv_longform_rules("nonexistent", episode(), context())


if __name__ == "__main__":
    unittest.main(verbosity=2)
