import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from type_registry import (
    ArtifactDescriptor, QualityRuleDescriptor, StageContract, TypePackDescriptor,
    WorkflowInputRequirement, WorkflowContract, parse_type_registry,
)


class TypeContractModelTests(unittest.TestCase):
    def test_artifact_origin_production_and_validation_are_explicit(self):
        artifact = ArtifactDescriptor(
            artifact_id="script", origin="workflow_output",
            production_stage="draft", validation_stages=["qa"],
            delivery_forms=["page_script"],
        )
        self.assertEqual(artifact.production_stage, "draft")
        self.assertEqual(artifact.validation_stages, ("qa",))
        with self.assertRaises(FrozenInstanceError):
            artifact.origin = "user_input"

    def test_stage_consumption_production_and_validation_are_separate(self):
        consumed = ["positioning"]
        stage = StageContract(
            stage_id="draft", consumes_artifact_ids=consumed,
            produces_artifact_ids=["script"], validates_artifact_ids=["outline"],
        )
        consumed.append("changed")
        self.assertEqual(stage.consumes_artifact_ids, ("positioning",))
        self.assertEqual(stage.produces_artifact_ids, ("script",))
        self.assertEqual(stage.validates_artifact_ids, ("outline",))
        with self.assertRaises(FrozenInstanceError):
            stage.stage_id = "other"

    def test_stage_runtime_semantics_are_immutable(self):
        stage = StageContract(
            stage_id="draft", stage_type="creation", owner="writer",
            gate="none", produces_artifact_ids=["script"],
        )
        self.assertEqual((stage.stage_type, stage.owner, stage.gate),
                         ("creation", "writer", "none"))
        with self.assertRaises(FrozenInstanceError):
            stage.stage_type = "validation"

    def test_positioning_can_be_input_without_producer(self):
        brief = ArtifactDescriptor(
            artifact_id="positioning", origin="user_input",
            input_stage="brief_gate", production_stage=None,
        )
        self.assertEqual(brief.origin, "user_input")
        self.assertIsNone(brief.production_stage)

    def test_optional_workflow_and_input_requirements_are_immutable(self):
        requirement = WorkflowInputRequirement("script", "approved")
        stages = [StageContract("illustration_init")]
        workflow = WorkflowContract(
            workflow_id="illustration", trigger_intent="illustration",
            inputs=[requirement], stages=stages, artifact_types=[],
            required=False, blocks_core_completion=False,
        )
        stages.clear()
        self.assertEqual(workflow.stages[0].stage_id, "illustration_init")
        self.assertEqual(workflow.inputs[0].required_status, "approved")
        with self.assertRaises(FrozenInstanceError):
            requirement.required_status = "draft"
        with self.assertRaises(FrozenInstanceError):
            workflow.blocks_core_completion = True

    def test_legacy_string_artifacts_normalize_to_descriptors(self):
        pack = parse_type_registry({"schema_version": 1, "packs": [{
            "medium_id": "picturebook", "aliases": [],
            "delivery_forms": ["page_script"],
            "artifact_types": ["script", "outline"],
            "workflow_policy": "picturebook-v1", "status": "active",
        }]}).packs[0]
        self.assertEqual(pack.artifact_ids, ("script", "outline"))
        self.assertTrue(all(isinstance(a, ArtifactDescriptor) for a in pack.artifact_types))

    def test_type_pack_collections_are_isolated(self):
        capabilities = ["illustration"]
        pack = TypePackDescriptor(
            medium_id="picturebook", aliases=[], delivery_forms=["page_script"],
            artifact_types=[], workflow_policy="picturebook-v1", status="active",
            version="picturebook-v1", capabilities=capabilities,
            optional_workflows=[],
        )
        capabilities.clear()
        self.assertEqual(pack.capabilities, ("illustration",))
        self.assertEqual(pack.optional_workflows, ())

    def test_quality_rule_descriptors_are_immutable_and_isolated(self):
        artifacts = ["script"]
        rule = QualityRuleDescriptor(
            check_id="project_authority", artifact_ids=artifacts,
            stage_id="preflight", blocking_policy="hard_block",
            validator="pre_output-baseline",
        )
        artifacts.append("outline")
        self.assertEqual(rule.artifact_ids, ("script",))
        with self.assertRaises(FrozenInstanceError):
            rule.blocking_policy = "advisory"


if __name__ == "__main__":
    unittest.main(verbosity=2)
