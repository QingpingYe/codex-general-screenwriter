import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_gate


class ReleaseGateTests(unittest.TestCase):
    def test_gate_passes_with_no_steps(self):
        self.assertEqual(run_release_gate(steps=()), 0)

    def test_gate_fails_when_offline_regression_fails(self):
        bad = [sys.executable, "-c", "raise SystemExit(1)"]
        self.assertEqual(
            run_release_gate(steps=(), paths=[bad]), 1)

    def test_gate_stops_on_first_failure(self):
        bad = [sys.executable, "-c", "raise SystemExit(1)"]
        reached = []
        def fake_run(command, **kwargs):
            reached.append(command)
            return 1
        original = release_gate._run_command
        release_gate._run_command = fake_run
        try:
            code = run_release_gate(steps=[
                ("step-a", [sys.executable, "-c", "pass"]),
                ("step-b", [sys.executable, "-c", "pass"]),
            ])
        finally:
            release_gate._run_command = original
        self.assertEqual(code, 1)
        self.assertEqual(len(reached), 1)

    def test_declares_gate_steps(self):
        self.assertEqual(
            [name for name, _ in release_gate.GATE_STEPS],
            ["registry_contract", "knowledge_adapter", "user_skill_trees",
             "user_skill_hub", "user_skill_runtime", "dag_scheduler",
             "quality_gate", "exporter_contract", "first_use_contract",
             "setup_docs_contract", "offline_regression", "governance_check",
             "packaging_check"],
        )

    def test_contract_declares_release_gate(self):
        import json
        contract = json.loads(
            (REPO_ROOT / "plugins" / "general-screenwriter" / "config" / "plugin-contract.json")
            .read_text(encoding="utf-8"))
        gate = contract["release_gate"]
        self.assertEqual(gate["schema_version"], "release-gate-v1")
        self.assertEqual(gate["script"], "scripts/release_gate.py")
        self.assertEqual(
            gate["steps"], [name for name, _ in release_gate.GATE_STEPS]
        )


def run_release_gate(**kwargs):
    return release_gate.run_release_gate(**kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
