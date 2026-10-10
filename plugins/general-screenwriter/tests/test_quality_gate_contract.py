import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from quality_gate_contract import (
    QualityCheckResult, build_quality_gate_report, quality_report_from_dict,
    quality_report_to_dict,
)
from type_registry import QualityRuleDescriptor


def rule(check_id="project_authority", artifact_ids=("script",),
         stage_id="preflight", blocking_policy="hard_block", validator=None):
    return QualityRuleDescriptor(
        check_id=check_id, artifact_ids=artifact_ids, stage_id=stage_id,
        blocking_policy=blocking_policy, validator=validator,
    )


def result(check_id="project_authority", status="pass", blocking_policy="hard_block",
           artifact_id="script", stage_id="preflight", **kwargs):
    return QualityCheckResult(
        check_id=check_id, artifact_id=artifact_id, stage_id=stage_id,
        blocking_policy=blocking_policy, status=status, **kwargs,
    )


class QualityGateContractTests(unittest.TestCase):
    def test_pass_report_is_confirmation_ready(self):
        report = build_quality_gate_report((rule(),), (result(),))
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)
        self.assertEqual(len(report.checks), 1)

    def test_hard_block_failure_blocks_confirmation(self):
        report = build_quality_gate_report(
            (rule(),), (result(status="fail", message="authority conflict"),)
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.confirmation_ready)
        self.assertEqual(len(report.blockers), 1)

    def test_user_confirmation_risk_is_not_silently_accepted(self):
        report = build_quality_gate_report(
            (rule(blocking_policy="require_user_confirmation", stage_id="qa"),),
            (result(blocking_policy="require_user_confirmation", stage_id="qa", status="fail"),),
        )
        self.assertTrue(report.passed)
        self.assertFalse(report.confirmation_ready)
        self.assertEqual(len(report.requires_user_confirmation), 1)

    def test_accepted_user_confirmation_risk_allows_confirmation(self):
        report = build_quality_gate_report(
            (rule(blocking_policy="require_user_confirmation", stage_id="qa"),),
            (result(
                blocking_policy="require_user_confirmation", stage_id="qa",
                status="fail", user_accepted=True,
            ),),
        )
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)

    def test_advisory_failure_is_warning_only(self):
        report = build_quality_gate_report(
            (rule(blocking_policy="advisory", stage_id="qa"),),
            (result(blocking_policy="advisory", stage_id="qa", status="fail"),),
        )
        self.assertTrue(report.passed)
        self.assertTrue(report.confirmation_ready)
        self.assertEqual(len(report.warnings), 1)

    def test_missing_and_invalid_results_are_unresolved_or_rejected(self):
        with self.assertRaises(ValueError):
            build_quality_gate_report((rule(),), ())
        with self.assertRaises(ValueError):
            build_quality_gate_report((rule(),), (
                result(), result(),
            ))
        with self.assertRaises(ValueError):
            build_quality_gate_report((rule(),), (
                result(artifact_id="outline"),
            ))
        with self.assertRaises(ValueError):
            build_quality_gate_report((rule(),), (
                result(stage_id="qa"),
            ))

    def test_json_round_trip(self):
        original = build_quality_gate_report(
            (rule(),),
            (result(status="fail", user_accepted=True, evidence={"page": 1}),),
        )
        restored = quality_report_from_dict(quality_report_to_dict(original))
        self.assertEqual(quality_report_to_dict(restored), quality_report_to_dict(original))


if __name__ == "__main__":
    unittest.main(verbosity=2)
