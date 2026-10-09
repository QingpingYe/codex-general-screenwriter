import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from type_registry import (  # noqa: E402
    ArtifactDescriptor,
    StageContract,
    TypePackDescriptor,
    parse_type_registry,
)


class TypeContractModelTests(unittest.TestCase):
    def test_artifact_and_stage_descriptors_are_immutable(self):
        artifact = ArtifactDescriptor(
            artifact_id="script",
            aliases=("screenplay",),
            delivery_forms=("page_script",),
            stage_id="draft",
            depends_on=("outline",),
            required=True,
            validator="script-v1",
            exporter=None,
            status="active",
        )
        stage = StageContract(
            stage_id="draft",
            aliases=("writing",),
            depends_on=("outline",),
            artifact_ids=("script",),
            confirmation_required=False,
            status="active",
        )
        with self.assertRaises(FrozenInstanceError):
            artifact.required = False
        with self.assertRaises(FrozenInstanceError):
            stage.stage_id = "other"
        self.assertEqual(artifact.depends_on, ("outline",))
        self.assertEqual(stage.artifact_ids, ("script",))

    def test_legacy_string_artifacts_normalize_to_descriptors(self):
        registry = parse_type_registry({
            "schema_version": 1,
            "packs": [{
                "medium_id": "picturebook",
                "aliases": [],
                "delivery_forms": ["page_script"],
                "artifact_types": ["script", "outline"],
                "workflow_policy": "picturebook-v1",
                "status": "active",
            }],
        })
        pack = registry.packs[0]
        self.assertEqual(pack.artifact_ids, ("script", "outline"))
        self.assertTrue(all(
            isinstance(artifact, ArtifactDescriptor)
            for artifact in pack.artifact_types
        ))
        self.assertEqual(pack.artifact_types[0].artifact_id, "script")

    def test_type_pack_descriptor_exposes_contract_collections(self):
        pack = TypePackDescriptor(
            medium_id="picturebook",
            version="picturebook-v1",
            aliases=(),
            delivery_forms=("page_script",),
            artifact_types=(),
            workflow_policy="picturebook-v1",
            status="active",
            stages=(),
            validators=(),
            exporters=(),
            capabilities=("illustration",),
        )
        self.assertEqual(pack.version, "picturebook-v1")
        self.assertEqual(pack.capabilities, ("illustration",))
        self.assertEqual(pack.artifact_ids, ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
