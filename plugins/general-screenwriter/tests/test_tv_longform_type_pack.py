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
import type_registry as tr
from creative_run_builder import CreativeRunRequest, build_creative_run
from screenwriter_context import CreativeContext
from tv_longform_checks import TV_LONGFORM_CHECK_IDS, validate_tv_longform_rules
from type_registry import load_type_registry, resolve_type_pack, validate_type_contract


CONTRACT = ROOT / "config" / "plugin-contract.json"


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


def episode(**overrides):
    artifact = {
        "artifact_id": "episode_script",
        "series_id": "s1",
        "season_arc": {"goal": "扳回一局", "obstacle": "内鬼", "turn": "盟友倒戈"},
        "episode_function": "推进主线：揭露内鬼线索。",
        "timeline": [{"order": 1, "event": "夜谈"}, {"order": 2, "event": "对峙"}],
        "foreshadows": [
            {"id": "f1", "source": "怀表停摆", "purpose": "第三集揭晓"},
        ],
        "payoffs": [
            {"foreshadow_id": "f1", "resolution": "怀表指向密室"},
        ],
        "scene_table": [
            {"scene": 1, "transition": "切至天台"},
        ],
        "character_states": [
            {"name": "林一", "state": "calm", "conflicts_with_previous": False},
        ],
        "continuity_ledger_ref": "series/s1/continuity",
    }
    artifact.update(overrides)
    return artifact


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

    def test_contract_reports_tv_longform_active(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("tv_longform", contract["type_pack_contract"]["active_medium_ids"])


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


class StructuralCheckTests(unittest.TestCase):
    def test_all_nine_checks_are_declared(self):
        self.assertEqual(
            set(TV_LONGFORM_CHECK_IDS),
            {"season_arc", "episode_function", "character_state", "timeline",
             "foreshadow", "payoff", "scene_transition", "series_constraint",
             "continuity"},
        )

    def test_well_formed_episode_passes_every_check(self):
        context = CreativeContext(
            "tv_longform", project_id="p1", series_id="s1", season_id="season-1")
        for check_id in TV_LONGFORM_CHECK_IDS:
            with self.subTest(check_id=check_id):
                result = validate_tv_longform_rules(check_id, episode(), context)
                self.assertEqual(result.status, "pass")

    def test_conflicting_character_state_is_reported_not_merged(self):
        context = CreativeContext(
            "tv_longform", project_id="p1", series_id="s1", season_id="season-1")
        conflicting = episode(character_states=[
            {"name": "林一", "state": "calm", "conflicts_with_previous": True},
        ])
        result = validate_tv_longform_rules("character_state", conflicting, context)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.evidence["conflicts"], ["s1:e1:character-state"])

    def test_each_check_fails_on_missing_field(self):
        context = CreativeContext(
            "tv_longform", project_id="p1", series_id="s1", season_id="season-1")
        cases = {
            "season_arc": {"season_arc": {}},
            "episode_function": {"episode_function": ""},
            "timeline": {"timeline": []},
            "foreshadow": {"foreshadows": []},
            "payoff": {"payoffs": []},
            "scene_transition": {"scene_table": []},
            "series_constraint": {"series_id": ""},
            "continuity": {"continuity_ledger_ref": ""},
        }
        for check_id, overrides in cases.items():
            with self.subTest(check_id=check_id):
                result = validate_tv_longform_rules(
                    check_id, episode(**overrides), context)
                self.assertEqual(result.status, "fail")

    def test_unknown_check_id_is_rejected(self):
        context = CreativeContext(
            "tv_longform", project_id="p1", series_id="s1", season_id="season-1")
        with self.assertRaises(ValueError):
            validate_tv_longform_rules("nonexistent", episode(), context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
