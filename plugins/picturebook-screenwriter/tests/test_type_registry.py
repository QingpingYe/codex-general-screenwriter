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


if __name__ == "__main__":
    unittest.main(verbosity=2)
