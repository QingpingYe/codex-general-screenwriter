import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from type_registry import (
    TypeRegistryError,
    load_type_registry,
    parse_type_registry,
    resolve_type_pack,
)


CONFIG = ROOT / "config" / "type-packs.json"


class TypeRegistryTests(unittest.TestCase):
    def test_loads_four_initial_mediums(self):
        registry = load_type_registry(CONFIG)
        self.assertEqual(
            {pack.medium_id for pack in registry.packs},
            {"picturebook", "film", "shortdrama", "tv_longform"},
        )

    def test_resolves_picturebook_alias(self):
        registry = load_type_registry(CONFIG)
        self.assertEqual(
            resolve_type_pack(registry, "picture book").medium_id,
            "picturebook",
        )

    def test_rejects_duplicate_aliases(self):
        payload = {"schema_version": 1, "packs": [
            {
                "medium_id": "film",
                "aliases": ["screen"],
                "delivery_forms": ["screenplay"],
                "artifact_types": [],
                "workflow_policy": "film-v1",
                "status": "planned",
            },
            {
                "medium_id": "shortdrama",
                "aliases": ["screen"],
                "delivery_forms": ["episode_script"],
                "artifact_types": [],
                "workflow_policy": "shortdrama-v1",
                "status": "planned",
            },
        ]}
        with self.assertRaises(TypeRegistryError):
            parse_type_registry(payload)

    def test_rejects_blank_alias(self):
        payload = {"schema_version": 1, "packs": [{
            "medium_id": "film",
            "aliases": ["  "],
            "delivery_forms": ["screenplay"],
            "artifact_types": [],
            "workflow_policy": "film-v1",
            "status": "planned",
        }]}
        with self.assertRaises(TypeRegistryError):
            parse_type_registry(payload)

    def test_rejects_alias_that_collides_with_another_medium_id(self):
        payload = {"schema_version": 1, "packs": [
            {
                "medium_id": "film",
                "aliases": ["shortdrama"],
                "delivery_forms": ["screenplay"],
                "artifact_types": [],
                "workflow_policy": "film-v1",
                "status": "planned",
            },
            {
                "medium_id": "shortdrama",
                "aliases": [],
                "delivery_forms": ["episode_script"],
                "artifact_types": [],
                "workflow_policy": "shortdrama-v1",
                "status": "planned",
            },
        ]}
        with self.assertRaises(TypeRegistryError):
            parse_type_registry(payload)

from type_registry import (  # noqa: E402
    ArtifactContractError,
    StageContractError,
    TypePackNotExecutableError,
    assert_type_pack_executable,
    resolve_artifact,
    resolve_stage,
)


class TypeContractRegistryTests(unittest.TestCase):
    def test_picturebook_has_complete_contract(self):
        registry = load_type_registry(CONFIG)
        pack = resolve_type_pack(registry, "picturebook")
        self.assertEqual(pack.version, "picturebook-v1")
        self.assertEqual(
            set(pack.artifact_ids),
            {
                "positioning", "topic_plan", "worldview", "characters",
                "outline", "script", "illustration_prompt_payload",
                "image_asset", "asset_registry", "html_preview",
            },
        )
        self.assertIn("session_init", {stage.stage_id for stage in pack.stages})
        self.assertIn("confirmation_gate", {stage.stage_id for stage in pack.stages})
        self.assertIn("illustration", pack.capabilities)

    def test_resolves_artifact_and_stage_by_alias(self):
        pack = resolve_type_pack(load_type_registry(CONFIG), "picturebook")
        self.assertEqual(resolve_artifact(pack, "final-script").artifact_id, "script")
        self.assertEqual(resolve_stage(pack, "drafting").stage_id, "creation_delegate")

    def test_unknown_artifact_and_stage_errors_are_distinct(self):
        pack = resolve_type_pack(load_type_registry(CONFIG), "picturebook")
        with self.assertRaises(ArtifactContractError):
            resolve_artifact(pack, "does-not-exist")
        with self.assertRaises(StageContractError):
            resolve_stage(pack, "does-not-exist")

    def test_planned_type_is_readable_but_not_executable(self):
        pack = resolve_type_pack(load_type_registry(CONFIG), "film")
        self.assertEqual(pack.status, "planned")
        with self.assertRaises(TypePackNotExecutableError):
            assert_type_pack_executable(pack)

    def test_rejects_unknown_stage_reference(self):
        payload = {
            "schema_version": 1,
            "packs": [{
                "medium_id": "film",
                "version": "film-v1",
                "aliases": [],
                "delivery_forms": ["screenplay"],
                "artifact_types": [{
                    "artifact_id": "screenplay",
                    "aliases": [],
                    "delivery_forms": ["screenplay"],
                    "stage_id": "draft",
                    "depends_on": [],
                    "required": True,
                    "validator": None,
                    "exporter": None,
                    "status": "planned",
                }],
                "stages": [],
                "workflow_policy": "film-v1",
                "status": "planned",
            }],
        }
        with self.assertRaises(StageContractError):
            parse_type_registry(payload)

    def test_rejects_unknown_artifact_dependency(self):
        payload = {
            "schema_version": 1,
            "packs": [{
                "medium_id": "film",
                "version": "film-v1",
                "aliases": [],
                "delivery_forms": ["screenplay"],
                "artifact_types": [{
                    "artifact_id": "screenplay",
                    "aliases": [],
                    "delivery_forms": ["screenplay"],
                    "stage_id": "draft",
                    "depends_on": ["missing"],
                    "required": True,
                    "validator": None,
                    "exporter": None,
                    "status": "planned",
                }],
                "stages": [{
                    "stage_id": "draft",
                    "aliases": [],
                    "depends_on": [],
                    "artifact_ids": ["screenplay"],
                    "confirmation_required": False,
                    "status": "planned",
                }],
                "workflow_policy": "film-v1",
                "status": "planned",
            }],
        }
        with self.assertRaises(ArtifactContractError):
            parse_type_registry(payload)

    def test_rejects_active_structured_pack_without_version(self):
        payload = {
            "schema_version": 1,
            "packs": [{
                "medium_id": "film",
                "aliases": [],
                "delivery_forms": ["screenplay"],
                "artifact_types": [{
                    "artifact_id": "screenplay",
                    "aliases": [],
                    "delivery_forms": ["screenplay"],
                    "stage_id": "draft",
                    "depends_on": [],
                    "required": True,
                    "validator": None,
                    "exporter": None,
                    "status": "active",
                }],
                "stages": [{
                    "stage_id": "draft",
                    "aliases": [],
                    "depends_on": [],
                    "artifact_ids": ["screenplay"],
                    "confirmation_required": False,
                    "status": "active",
                }],
                "workflow_policy": "film-v1",
                "status": "active",
            }],
        }
        with self.assertRaises(TypeRegistryError):
            parse_type_registry(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)

