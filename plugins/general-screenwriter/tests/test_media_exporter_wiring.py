import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from type_registry import (
    load_type_registry,
    resolve_type_pack,
    validate_type_contract,
)


EXPORTERS = ROOT / "config" / "exporters.json"


def config_entries():
    payload = json.loads(EXPORTERS.read_text(encoding="utf-8"))
    return {item["exporter_id"]: item for item in payload["exporters"]}


class MediaExporterWiringTests(unittest.TestCase):
    def test_every_registered_media_exporter_has_config_entry(self):
        declared = set(config_entries())
        registry = load_type_registry()
        for medium in ("shortdrama", "tv_longform"):
            pack = resolve_type_pack(registry, medium)
            with self.subTest(medium=medium):
                self.assertTrue(pack.exporters)
                self.assertLessEqual(set(pack.exporters), declared)

    def test_episode_script_artifact_declares_its_exporter(self):
        registry = load_type_registry()
        expectations = {
            "shortdrama": "shortdrama_episode_script",
            "tv_longform": "tv_episode_script",
        }
        for medium, exporter_id in expectations.items():
            pack = resolve_type_pack(registry, medium)
            artifact = next(
                item for item in pack.artifact_types
                if item.artifact_id == "episode_script"
            )
            with self.subTest(medium=medium):
                self.assertEqual(artifact.exporter, exporter_id)

    def test_shortdrama_scene_table_declares_checklist_exporter(self):
        pack = resolve_type_pack(load_type_registry(), "shortdrama")
        artifact = next(
            item for item in pack.artifact_types
            if item.artifact_id == "scene_table"
        )
        self.assertEqual(artifact.exporter, "shortdrama_production_checklist")

    def test_contract_validation_accepts_wired_packs(self):
        registry = load_type_registry()
        for medium in ("picturebook", "shortdrama", "tv_longform"):
            pack = resolve_type_pack(registry, medium)
            with self.subTest(medium=medium):
                self.assertEqual(validate_type_contract(pack), pack)

    def test_pack_exporter_lists_stay_scoped(self):
        registry = load_type_registry()
        shortdrama = resolve_type_pack(registry, "shortdrama")
        tv_longform = resolve_type_pack(registry, "tv_longform")
        picturebook = resolve_type_pack(registry, "picturebook")
        self.assertEqual(
            set(shortdrama.exporters),
            {"shortdrama_episode_script", "shortdrama_production_checklist",
             "structured_json"},
        )
        self.assertEqual(
            set(tv_longform.exporters),
            {"tv_episode_script", "tv_season_package", "structured_json"},
        )
        self.assertEqual(set(picturebook.exporters), {"illustration-export"})

    def test_new_exporter_entries_are_fail_closed(self):
        entries = config_entries()
        for exporter_id in (
            "shortdrama_episode_script", "shortdrama_production_checklist",
            "tv_episode_script", "tv_season_package", "structured_json",
        ):
            with self.subTest(exporter=exporter_id):
                entry = entries[exporter_id]
                self.assertEqual(entry["validation_policy"], "fail_closed")
                self.assertEqual(entry["confirmation_policy"], "explicit_params_only")
                self.assertEqual(entry.get("model_calls", "forbidden"), "forbidden")
                self.assertIn("filename", entry["required_user_params"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
