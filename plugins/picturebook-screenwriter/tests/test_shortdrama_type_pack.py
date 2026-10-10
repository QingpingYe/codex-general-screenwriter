import copy
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
import type_registry as tr
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


def episode(**overrides):
    artifact = {
        "artifact_id": "episode_script",
        "opening_hook": "前3秒：她推开天台的门，风把 Evidence 吹散。",
        "closing_hook": "他回头，手机屏幕亮起：定位已共享。",
        "turning_point": "替身身份在直播中被揭穿。",
        "beats": [
            {"beat": 1, "conflict": "对峙"},
            {"beat": 2, "conflict": "反转"},
        ],
        "conflict": {"goal": "夺回证据", "closed": True},
        "characters": [{"name": "林一", "state": "calm"}],
        "format": "episode_script",
        "duration_seconds": 120,
    }
    artifact.update(overrides)
    return artifact


class ConfigContractTests(unittest.TestCase):
    def test_config_keeps_shortdrama_planned_with_full_contract(self):
        pack = config_pack()
        self.assertEqual(pack.status, "planned")
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

    def test_config_pack_is_not_dispatchable(self):
        manifest = stage_dag.attach_context(
            stage_dag._creation_template_manifest(),
            CreativeContext("shortdrama", project_id="p1",
                            delivery_form="episode_script"),
            {"type_pack": {"medium_id": "shortdrama", "version": "shortdrama-v1"}},
        )
        with self.assertRaises(tr.TypePackNotExecutableError):
            stage_dag_codex.build_dispatch_plan(manifest)

    def test_contract_still_reports_shortdrama_planned(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("shortdrama", contract["type_pack_contract"]["planned_medium_ids"])
        self.assertNotIn("shortdrama", contract["type_pack_contract"]["active_medium_ids"])


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
            build_creative_run(request(type_pack=config_pack()))


class StructuralCheckTests(unittest.TestCase):
    def test_all_eight_checks_are_declared(self):
        self.assertEqual(
            set(SHORTDRAMA_CHECK_IDS),
            {"opening_hook", "turning_point", "closing_hook", "pacing_density",
             "conflict_closure", "character_state", "format", "duration"},
        )

    def test_well_formed_episode_passes_every_check(self):
        context = CreativeContext("shortdrama", project_id="p1",
                                  delivery_form="episode_script")
        for check_id in SHORTDRAMA_CHECK_IDS:
            with self.subTest(check_id=check_id):
                result = validate_shortdrama_rules(check_id, episode(), context)
                self.assertEqual(result.status, "pass")

    def test_missing_closing_hook_fails_user_confirmation_risk(self):
        context = CreativeContext("shortdrama", project_id="p1",
                                  delivery_form="episode_script")
        result = validate_shortdrama_rules(
            "closing_hook", episode(closing_hook=""), context)
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

    def test_each_check_fails_on_missing_field(self):
        context = CreativeContext("shortdrama", project_id="p1",
                                  delivery_form="episode_script")
        cases = {
            "opening_hook": {"opening_hook": ""},
            "turning_point": {"turning_point": None},
            "pacing_density": {"beats": []},
            "conflict_closure": {"conflict": {"goal": "x", "closed": False}},
            "character_state": {"characters": []},
            "format": {"format": "screenplay"},
            "duration": {"duration_seconds": 0},
        }
        for check_id, overrides in cases.items():
            with self.subTest(check_id=check_id):
                result = validate_shortdrama_rules(
                    check_id, episode(**overrides), context)
                self.assertEqual(result.status, "fail")

    def test_unknown_check_id_is_rejected(self):
        context = CreativeContext("shortdrama", project_id="p1",
                                  delivery_form="episode_script")
        with self.assertRaises(ValueError):
            validate_shortdrama_rules("nonexistent", episode(), context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
