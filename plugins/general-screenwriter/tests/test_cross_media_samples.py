import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
import stage_dag_codex
from sample_workflow import load_sample, run_sample_workflow
from screenwriter_context import CreativeContext
from type_registry import load_type_registry, resolve_type_pack


FIXTURES = ROOT / "tests" / "fixtures"
CONTRACT = ROOT / "config" / "plugin-contract.json"


class CrossMediaSampleTests(unittest.TestCase):
    def test_picturebook_pass_sample_confirms(self):
        result = run_sample_workflow(load_sample(FIXTURES / "picturebook-pass.json"))
        self.assertTrue(result.confirmation_ready)

    def test_picturebook_fail_sample_is_confirmation_blocked(self):
        result = run_sample_workflow(load_sample(FIXTURES / "picturebook-fail.json"))
        self.assertTrue(result.report.passed)
        self.assertFalse(result.confirmation_ready)
        self.assertTrue(result.report.requires_user_confirmation)
        self.assertIsNotNone(result.failure_reason)

    def test_shortdrama_pass_sample_confirms(self):
        result = run_sample_workflow(load_sample(FIXTURES / "shortdrama-pass.json"))
        self.assertTrue(result.report.passed)
        self.assertTrue(result.confirmation_ready)

    def test_shortdrama_fail_sample_is_confirmation_blocked(self):
        result = run_sample_workflow(load_sample(FIXTURES / "shortdrama-fail.json"))
        self.assertTrue(result.report.passed)
        self.assertFalse(result.confirmation_ready)
        self.assertIsNotNone(result.failure_reason)

    def test_tv_longform_pass_sample_confirms(self):
        result = run_sample_workflow(load_sample(FIXTURES / "tv-longform-pass.json"))
        self.assertTrue(result.report.passed)
        self.assertTrue(result.confirmation_ready)

    def test_tv_longform_fail_sample_is_hard_blocked(self):
        result = run_sample_workflow(load_sample(FIXTURES / "tv-longform-fail.json"))
        self.assertFalse(result.report.passed)
        self.assertFalse(result.confirmation_ready)
        self.assertEqual(
            [item.check_id for item in result.report.blockers],
            ["character_state"],
        )

    def test_sample_contexts_match_current_packs(self):
        for name in ("picturebook-pass.json", "shortdrama-pass.json", "tv-longform-pass.json"):
            sample = load_sample(FIXTURES / name)
            pack = resolve_type_pack(load_type_registry(), sample.medium)
            with self.subTest(name=name):
                self.assertEqual(sample.context["medium_id"], pack.medium_id)
                self.assertIsNotNone(pack.version)


class MediaActivationTests(unittest.TestCase):
    def test_all_three_media_are_active(self):
        registry = load_type_registry()
        for medium in ("picturebook", "shortdrama", "tv_longform"):
            with self.subTest(medium=medium):
                pack = resolve_type_pack(registry, medium)
                self.assertEqual(pack.status, "active")

    def test_shortdrama_minimal_run_is_ready_from_config(self):
        pack = resolve_type_pack(load_type_registry(), "shortdrama")
        manifest = stage_dag.validate_manifest({
            "schema_version": stage_dag.RUN_SCHEMA,
            "run_id": "activation-sd-1",
            "root_run_id": "activation-sd-1",
            "revision_of_run_id": None,
            "iteration": 1,
            "intent": "creation",
            "artifact_type": "episode_script",
            "mode": "full",
            "project_root": str(REPO_ROOT),
            "status": "pending",
            "outcome": None,
            "revision_feedback": [],
            "source_artifact_ref": None,
            "context": stage_dag.context_to_dict(CreativeContext(
                "shortdrama", project_id="p1", delivery_form="episode_script")),
            "resolution_snapshot": {
                "type_pack": {"medium_id": "shortdrama", "version": pack.version},
            },
            "stages": [
                {
                    "stage_id": item.stage_id,
                    "assignee": item.owner,
                    "stage_type": item.stage_type,
                    "depends_on": list(item.depends_on),
                    "status": "pending",
                    "gate": item.gate,
                    "outcome": None,
                    "when": None,
                    "input_refs": [],
                    "output_refs": [],
                    "skip_reason": None,
                    "blocked_reason": None,
                }
                for item in pack.stages
            ],
        })
        self.assertEqual(stage_dag.ready_stages(manifest), ["session_init"])

    def test_tv_longform_minimal_run_is_ready_from_config(self):
        pack = resolve_type_pack(load_type_registry(), "tv_longform")
        manifest = stage_dag.validate_manifest({
            "schema_version": stage_dag.RUN_SCHEMA,
            "run_id": "activation-tv-1",
            "root_run_id": "activation-tv-1",
            "revision_of_run_id": None,
            "iteration": 1,
            "intent": "creation",
            "artifact_type": "episode_script",
            "mode": "full",
            "project_root": str(REPO_ROOT),
            "status": "pending",
            "outcome": None,
            "revision_feedback": [],
            "source_artifact_ref": None,
            "context": stage_dag.context_to_dict(CreativeContext(
                "tv_longform", project_id="p1", series_id="s1",
                season_id="season-1", delivery_form="season_episode_script")),
            "resolution_snapshot": {
                "type_pack": {"medium_id": "tv_longform", "version": pack.version},
            },
            "stages": [
                {
                    "stage_id": item.stage_id,
                    "assignee": item.owner,
                    "stage_type": item.stage_type,
                    "depends_on": list(item.depends_on),
                    "status": "pending",
                    "gate": item.gate,
                    "outcome": None,
                    "when": None,
                    "input_refs": [],
                    "output_refs": [],
                    "skip_reason": None,
                    "blocked_reason": None,
                }
                for item in pack.stages
            ],
        })
        self.assertEqual(stage_dag.ready_stages(manifest), ["session_init"])

    def test_contract_reports_three_active_media(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        type_contract = contract["type_pack_contract"]
        self.assertEqual(
            set(type_contract["active_medium_ids"]),
            {"picturebook", "shortdrama", "tv_longform"},
        )
        self.assertEqual(type_contract["planned_medium_ids"], [])
        self.assertEqual(contract["creative_workflow"]["planned_medium_ids"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
