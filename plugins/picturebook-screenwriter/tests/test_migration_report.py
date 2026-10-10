import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from migration_report import (
    MigrationReport,
    build_migration_report,
    report_to_dict,
)


class MigrationReportTests(unittest.TestCase):
    def test_old_knowledge_key_is_reported_v1_compatible_not_rewritten(self):
        inventory = [
            {"key": "s1/p1/worldview", "status": "v1_compatible"},
            {"key": "project/p1/worldview", "status": "matched"},
        ]
        report = build_migration_report("knowledge_key", 1, 2, inventory)
        self.assertIsInstance(report, MigrationReport)
        self.assertEqual(report.source_kind, "knowledge_key")
        self.assertEqual(report.source_version, 1)
        self.assertEqual(report.target_version, 2)
        self.assertEqual(report.items[0].key, "s1/p1/worldview")
        self.assertEqual(report.items[0].status, "v1_compatible")
        self.assertEqual(report.rollback["writes"], 0)

    def test_entries_without_keys_are_missing(self):
        report = build_migration_report("run_manifest", 2, 3, [{"status": "matched"}, "junk"])
        statuses = [item.status for item in report.items]
        self.assertIn("missing", statuses)

    def test_ambiguous_entries_are_flagged_with_manual_actions(self):
        report = build_migration_report("artifact_id", 1, 2, [
            {"key": "old-artifact", "status": "ambiguous", "detail": "两个候选目标"},
        ])
        self.assertEqual(report.items[0].status, "ambiguous")
        self.assertTrue(any("old-artifact" in action for action in report.manual_actions))

    def test_report_to_dict_round_trip_shape(self):
        report = build_migration_report("export_path", 1, 2, [
            {"key": "out/preview.html", "status": "matched"},
        ])
        payload = report_to_dict(report)
        self.assertEqual(payload["source_kind"], "export_path")
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["rollback"]["mode"], "read_only")

    def test_all_six_standard_source_kinds_accepted(self):
        for kind in ("run_manifest", "artifact_id", "knowledge_key",
                     "skill_reference", "illustration_flow", "export_path"):
            with self.subTest(kind=kind):
                report = build_migration_report(kind, 1, 2, [])
                self.assertEqual(report.source_kind, kind)


if __name__ == "__main__":
    unittest.main(verbosity=2)
