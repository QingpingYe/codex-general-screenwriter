import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from setup_state import SetupCheck, render_setup_report


class SetupStateTests(unittest.TestCase):
    def test_report_preserves_independent_checks_and_first_blocker(self):
        checks = (
            SetupCheck(
                "cli", "ready", None, "CLI is ready", (), None,
            ),
            SetupCheck(
                "target", "waiting_initializer", "control_tree_missing",
                "the designated maintainer must initialize the target",
                ("preview initialization",), "Confirm the target maintainer",
            ),
            SetupCheck(
                "write", "write_verification_required", None,
                "write acceptance has not been performed", (), None,
            ),
        )

        report = render_setup_report(checks)

        self.assertEqual(report["schema_version"], 1)
        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "waiting_initializer")
        self.assertEqual([check["check_id"] for check in report["checks"]], [
            "cli", "target", "write",
        ])
        self.assertEqual(report["checks"][1]["ai_next_actions"], [
            "preview initialization",
        ])
        self.assertEqual(report["blocking_checks"], ["target", "write"])

    def test_report_is_ready_only_when_every_check_is_ready(self):
        checks = (
            SetupCheck("cli", "ready", None, "CLI is ready", (), None),
            SetupCheck("target", "ready", None, "target is ready", (), None),
        )

        report = render_setup_report(checks)

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["blocking_checks"], [])

    def test_empty_report_requires_context(self):
        report = render_setup_report(())

        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "needs_context")
        self.assertEqual(report["checks"], [])


if __name__ == "__main__":
    unittest.main()
