"""Unified release gate: run the ordered release checks, stop on first failure."""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

GATE_STEPS = (
    ("registry_contract", "plugins/general-screenwriter/tests/test_type_registry.py"),
    ("knowledge_adapter", "plugins/general-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py"),
    ("user_skill_trees", "scripts/user_skill_gate.py"),
    ("user_skill_hub", "plugins/general-screenwriter/tests/test_user_skill_hub.py"),
    ("user_skill_runtime", "plugins/general-screenwriter/tests/test_user_skill_run_integration.py"),
    ("dag_scheduler", "plugins/general-screenwriter/tests/test_stage_dag.py"),
    ("quality_gate", "plugins/general-screenwriter/tests/test_quality_gate_contract.py"),
    ("exporter_contract", "plugins/general-screenwriter/tests/test_exporter_contract.py"),
    ("dual_harness_contract", "plugins/general-screenwriter/tests/test_dual_harness_contract.py"),
    ("first_use_contract", "plugins/general-screenwriter/tests/test_first_use_release_contract.py"),
    ("setup_docs_contract", "plugins/general-screenwriter/tests/test_setup_contract.py"),
    ("offline_regression", "scripts/run_plugin_tests.py"),
    ("governance_check", "scripts/governance_check.py"),
    ("packaging_check", "scripts/package_check.py"),
)


def _run_command(command) -> int:
    completed = subprocess.run(command, cwd=str(REPO_ROOT))
    return completed.returncode


def run_release_gate(paths=(), verbose: bool = False, steps=None) -> int:
    if steps is None:
        steps = GATE_STEPS
    commands: list[tuple[str, list[str]]] = [
        (name, [sys.executable, str(REPO_ROOT / script)]
         if isinstance(script, str)
         else [str(part) for part in script])
        for name, script in steps
    ]
    for extra in paths:
        commands.append(("user_check", [str(part) for part in extra]))
    for name, command in commands:
        print(f"[release-gate] {name} ...", flush=True)
        code = _run_command(command)
        if code != 0:
            print(f"[release-gate] {name} FAILED (exit {code})")
            return 1
        if verbose:
            print(f"[release-gate] {name} ok")
    print("[release-gate] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_release_gate())
