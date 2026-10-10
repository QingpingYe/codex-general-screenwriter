import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
import stage_dag_codex
from quality_gate_contract import QualityCheckResult, build_quality_gate_report
from screenwriter_context import CreativeContext
from type_registry import (
    QualityRuleDescriptor,
    load_type_registry,
    resolve_artifact,
    resolve_type_pack,
)


FIXTURES = ROOT / "tests" / "fixtures"
CONTRACT = ROOT / "config" / "plugin-contract.json"

_SAMPLE_REQUIRED = {
    "medium", "context", "target_artifact", "workflow_inputs",
    "knowledge_scope", "quality_rules", "expected_results", "failure_reason",
}


@dataclass(frozen=True)
class SampleContract:
    medium: str
    context: Mapping[str, Any]
    target_artifact: str
    workflow_inputs: tuple[Mapping[str, Any], ...]
    knowledge_scope: Mapping[str, Any]
    quality_rules: tuple[Mapping[str, Any], ...]
    expected_results: tuple[Mapping[str, Any], ...]
    failure_reason: str | None


def load_sample(path: Path) -> SampleContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not _SAMPLE_REQUIRED <= set(payload) or set(payload) != _SAMPLE_REQUIRED:
        raise ValueError(f"sample fixture fields invalid: {path.name}")
    for rule in payload["quality_rules"]:
        if set(rule) != {"check_id", "artifact_ids", "stage_id", "blocking_policy", "validator"}:
            raise ValueError(f"sample fixture rule fields invalid: {path.name}")
    for expected in payload["expected_results"]:
        if set(expected) != {"check_id", "status"}:
            raise ValueError(f"sample fixture expected fields invalid: {path.name}")
    return SampleContract(
        medium=payload["medium"],
        context=dict(payload["context"]),
        target_artifact=payload["target_artifact"],
        workflow_inputs=tuple(dict(item) for item in payload["workflow_inputs"]),
        knowledge_scope=dict(payload["knowledge_scope"]),
        quality_rules=tuple(dict(item) for item in payload["quality_rules"]),
        expected_results=tuple(dict(item) for item in payload["expected_results"]),
        failure_reason=payload["failure_reason"],
    )


def _canonical_rule(rule: Mapping[str, Any]) -> dict:
    return {
        "check_id": rule["check_id"],
        "artifact_ids": list(rule["artifact_ids"]),
        "stage_id": rule["stage_id"],
        "blocking_policy": rule["blocking_policy"],
        "validator": rule["validator"],
    }


def evaluate_sample(sample: SampleContract):
    pack = resolve_type_pack(load_type_registry(), sample.medium)
    artifact = resolve_artifact(pack, sample.target_artifact)
    pack_rules = sorted(
        (_canonical_rule(vars(rule)) for rule in pack.quality_rules
         if sample.target_artifact in rule.artifact_ids),
        key=lambda rule: rule["check_id"],
    )
    fixture_rules = sorted(
        (_canonical_rule(rule) for rule in sample.quality_rules),
        key=lambda rule: rule["check_id"],
    )
    if pack_rules != fixture_rules:
        raise AssertionError(
            f"sample rules drift from current {sample.medium} pack for {sample.target_artifact}"
        )
    descriptors = {
        rule["check_id"]: QualityRuleDescriptor(
            check_id=rule["check_id"],
            artifact_ids=tuple(rule["artifact_ids"]),
            stage_id=rule["stage_id"],
            blocking_policy=rule["blocking_policy"],
            validator=rule["validator"],
        )
        for rule in sample.quality_rules
    }
    expected = {item["check_id"]: item["status"] for item in sample.expected_results}
    if set(expected) != set(descriptors):
        raise AssertionError("sample expected_results must cover every declared rule")
    results = [
        QualityCheckResult(
            check_id=rule["check_id"],
            artifact_id=sample.target_artifact,
            stage_id=rule["stage_id"],
            blocking_policy=rule["blocking_policy"],
            status=expected[rule["check_id"]],
            evidence={"source": "fixture", "knowledge_scope": dict(sample.knowledge_scope)},
        )
        for rule in sorted(sample.quality_rules, key=lambda item: item["check_id"])
    ]
    return build_quality_gate_report(
        descriptors.values(),
        results,
        gate_id=f"{sample.medium}-sample",
        scope="sample",
    )


def sample_path(name: str) -> Path:
    return FIXTURES / name


class CrossMediaSampleTests(unittest.TestCase):
    def test_picturebook_pass_sample_confirms(self):
        sample = load_sample(sample_path("picturebook-pass.json"))
        report = evaluate_sample(sample)
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)

    def test_picturebook_fail_sample_is_confirmation_blocked(self):
        sample = load_sample(sample_path("picturebook-fail.json"))
        report = evaluate_sample(sample)
        self.assertTrue(report.passed)
        self.assertFalse(report.confirmation_ready)
        self.assertTrue(report.requires_user_confirmation)
        self.assertIsNotNone(sample.failure_reason)

    def test_shortdrama_pass_sample_confirms(self):
        sample = load_sample(sample_path("shortdrama-pass.json"))
        report = evaluate_sample(sample)
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)

    def test_shortdrama_fail_sample_is_confirmation_blocked(self):
        sample = load_sample(sample_path("shortdrama-fail.json"))
        report = evaluate_sample(sample)
        self.assertTrue(report.passed)
        self.assertFalse(report.confirmation_ready)
        self.assertIsNotNone(sample.failure_reason)

    def test_tv_longform_pass_sample_confirms(self):
        sample = load_sample(sample_path("tv-longform-pass.json"))
        report = evaluate_sample(sample)
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)

    def test_tv_longform_fail_sample_is_hard_blocked(self):
        sample = load_sample(sample_path("tv-longform-fail.json"))
        report = evaluate_sample(sample)
        self.assertFalse(report.passed)
        self.assertFalse(report.confirmation_ready)
        self.assertEqual(
            [item.check_id for item in report.blockers],
            ["character_state"],
        )

    def test_sample_contexts_match_current_packs(self):
        for name in ("picturebook-pass.json", "shortdrama-pass.json", "tv-longform-pass.json"):
            sample = load_sample(sample_path(name))
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
