import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
from creative_run_builder import CreativeRunRequest, build_creative_run
from screenwriter_context import CreativeContext
from type_registry import (
    ArtifactDescriptor, QualityRuleDescriptor, StageContract,
    load_type_registry, resolve_type_pack,
)


def artifact(aid, **kwargs):
    values = dict(
        artifact_id=aid, aliases=[], delivery_forms=[aid], depends_on=[],
        origin="workflow_output", input_stage=None, production_stage=f"{aid}_delegate",
        validation_stages=["qa"], validator=None, exporter=None, status="active",
    )
    values.update(kwargs)
    return ArtifactDescriptor(**values)


def stage(sid, **kwargs):
    values = dict(
        stage_id=sid, aliases=[], depends_on=[], consumes_artifact_ids=[],
        produces_artifact_ids=[], validates_artifact_ids=[],
        confirmation_required=False, status="active", stage_type="validation",
        owner="owner", gate="none",
    )
    values.update(kwargs)
    return StageContract(**values)


def generic_pack():
    planned = resolve_type_pack(load_type_registry(), "shortdrama")
    return replace(
        planned,
        version="shortdrama-fixture-v1",
        status="active",
        artifact_types=(
            artifact("positioning", delivery_forms=["episode_script"],
                     origin="user_input", input_stage="brief_gate",
                     production_stage=None, validation_stages=[]),
            artifact("episode_script"),
        ),
        stages=(
            stage("session_init", stage_type="session_init"),
            stage("brief_gate", stage_type="brief_gate", gate="brief",
                  depends_on=["session_init"],
                  consumes_artifact_ids=["positioning"]),
            stage("knowledge_load", stage_type="knowledge_load", gate="authority"),
            stage("episode_script_delegate", stage_type="creation", owner="writer",
                  depends_on=["brief_gate", "knowledge_load"],
                  consumes_artifact_ids=["positioning"],
                  produces_artifact_ids=["episode_script"]),
            stage("qa", stage_type="validation", owner="quality", gate="quality",
                  depends_on=["episode_script_delegate"],
                  validates_artifact_ids=["episode_script"]),
            stage("confirmation_gate", stage_type="confirmation", owner="lead",
                  gate="confirmation", confirmation_required=True,
                  depends_on=["qa"]),
            stage("persistence", stage_type="persistence", owner="persistence",
                  depends_on=["confirmation_gate"],
                  consumes_artifact_ids=["episode_script"]),
        ),
        quality_rules=(
            QualityRuleDescriptor(
                check_id="format", artifact_ids=("episode_script",),
                stage_id="qa", blocking_policy="hard_block",
            ),
        ),
    )


def request(pack=None, **kwargs):
    values = dict(
        type_pack=pack or generic_pack(),
        context=CreativeContext("shortdrama", project_id="p1",
                                delivery_form="episode_script"),
        intent="creation", target="episode_script", run_id="run-1",
        project_root=str(REPO_ROOT),
    )
    values.update(kwargs)
    return CreativeRunRequest(**values)


class CreativeRunBuilderTests(unittest.TestCase):
    def test_builds_nonpicturebook_core_run_from_type_pack(self):
        manifest = build_creative_run(request())
        self.assertEqual(manifest["artifact_type"], "episode_script")
        self.assertEqual(manifest["intent"], "creation")
        self.assertEqual(
            [item["stage_id"] for item in manifest["stages"]],
            [item.stage_id for item in generic_pack().stages],
        )
        self.assertEqual(manifest["stages"][3]["assignee"], "writer")
        self.assertEqual(manifest["stages"][3]["gate"], "none")
        self.assertEqual(manifest["stages"][3]["stage_type"], "creation")

    def test_skills_resolution_lands_in_snapshot_and_stays_isolated(self):
        skills = [{
            "skill_id": "project-hook-checklist",
            "version": "1.0.0",
            "authority": "project_skill",
            "scopes": [{"scope_type": "project", "project_id": "p1"}],
            "stage_id": "qa",
            "execution_policy": "advisory",
            "status": "active",
            "content_hash": "abc123def456",
        }]
        manifest = build_creative_run(request(skills_resolution=skills))
        self.assertEqual(manifest["resolution_snapshot"]["skills"], skills)
        manifest["resolution_snapshot"]["skills"][0]["skill_id"] = "mutated"
        self.assertEqual(skills[0]["skill_id"], "project-hook-checklist")
        self.assertEqual(
            manifest["resolution_snapshot"]["type_pack"],
            {"medium_id": "shortdrama", "version": "shortdrama-fixture-v1",
             "workflow_policy": "shortdrama-v1"},
        )
        self.assertEqual(
            manifest["resolution_snapshot"]["quality_rules"],
            [{"check_id": "format", "artifact_ids": ["episode_script"],
              "stage_id": "qa", "blocking_policy": "hard_block", "validator": None}],
        )
        stage_dag.validate_manifest(manifest)
        self.assertIn("session_init", stage_dag.topological_order(manifest))

    def test_builds_generic_revision_with_required_lineage(self):
        manifest = build_creative_run(request(
            intent="revision", target="episode_script", run_id="run-2",
            root_run_id="run-root", revision_of_run_id="run-1",
            revision_iteration=2,
            revision_feedback=[{"issue": "pacing", "instruction": "tighten"}],
            source_artifact_ref="output/script_v1.md",
        ))
        self.assertEqual(manifest["intent"], "revision")
        self.assertEqual(manifest["revision_of_run_id"], "run-1")
        self.assertEqual(manifest["iteration"], 2)
        self.assertEqual(
            [item["stage_id"] for item in manifest["stages"]],
            [item.stage_id for item in generic_pack().stages],
        )
        self.assertEqual(manifest["stages"][5]["gate"], "confirmation")

    def test_rejects_planned_pack_before_manifest_construction(self):
        planned = replace(resolve_type_pack(load_type_registry(), "shortdrama"),
                          status="planned")
        with self.assertRaises(stage_dag.StageDagError):
            build_creative_run(request(planned))

    def test_rejects_invalid_target_and_missing_runtime_metadata(self):
        with self.assertRaises(stage_dag.StageDagError):
            build_creative_run(request(target="unknown"))
        with self.assertRaises(stage_dag.StageDagError):
            build_creative_run(request(target="positioning"))
        bad_pack = generic_pack()
        bad = replace(
            bad_pack,
            stages=tuple(
                replace(item, owner=None) if item.stage_id == "session_init" else item
                for item in bad_pack.stages
            ),
        )
        with self.assertRaises(stage_dag.StageDagError):
            build_creative_run(request(bad))

    def test_request_is_not_mutated_by_builder(self):
        original = request()
        feedback = [{"issue": "hook", "instruction": "revise"}]
        manifest = build_creative_run(request(
            intent="revision", target="episode_script", run_id="run-2",
            root_run_id="root", revision_of_run_id="run-1", revision_iteration=2,
            revision_feedback=feedback, source_artifact_ref="output/script_v1.md",
        ))
        manifest["stages"][0]["owner"] = "changed"
        self.assertEqual(feedback, [{"issue": "hook", "instruction": "revise"}])

    def test_legacy_revision_keeps_explicit_template_shape(self):
        manifest = stage_dag._revision_template_manifest()
        self.assertIn("revision_init", [item["stage_id"] for item in manifest["stages"]])
        self.assertIn("revision_delegate", [item["stage_id"] for item in manifest["stages"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
