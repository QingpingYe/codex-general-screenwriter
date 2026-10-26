import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_contract import (
    MIN_LARK_CLI_VERSION,
    REQUIRED_CAPABILITIES,
    detect_capabilities,
    inspect_capabilities,
    parse_version,
    version_meets_minimum,
)


class Completed:
    def __init__(self, returncode=0):
        self.stdout = ""
        self.stderr = ""
        self.returncode = returncode


class CapabilityRunner:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return Completed(result)


class LarkCliContractTests(unittest.TestCase):
    def test_minimum_version_is_one_stable_floor(self):
        self.assertEqual(MIN_LARK_CLI_VERSION, "1.0.95")

    def test_stable_versions_at_or_above_minimum_are_accepted(self):
        for version in ("1.0.95", "1.0.96", "1.0.98", "1.0.100", "1.1.0", "2.0.0"):
            with self.subTest(version=version):
                self.assertTrue(version_meets_minimum(version))
        self.assertTrue(version_meets_minimum("1.0.95+build.1"))

    def test_older_or_prerelease_versions_are_rejected(self):
        for version in ("1.0.94", "1.0.95-rc.1"):
            with self.subTest(version=version):
                self.assertFalse(version_meets_minimum(version))

    def test_parse_version_returns_numeric_components(self):
        self.assertEqual(parse_version("1.0.100"), (1, 0, 100))
        self.assertEqual(parse_version("lark-cli version 2.1.0"), (2, 1, 0))
        self.assertEqual(parse_version("lark-cli/1.0.96"), (1, 0, 96))

    def test_parse_version_returns_none_for_unparseable_or_prerelease_text(self):
        self.assertIsNone(parse_version("unparseable"))
        self.assertIsNone(parse_version("1.0.95-rc.1"))
        self.assertIsNone(parse_version("Node v22.10.0"))

    def test_parse_version_uses_lark_cli_context_in_mixed_output(self):
        self.assertEqual(
            parse_version("Node v22.10.0\nlark-cli version 1.0.94\n"),
            (1, 0, 94),
        )

    def test_parse_version_rejects_ambiguous_lark_cli_output(self):
        self.assertIsNone(
            parse_version("lark-cli version 1.0.95\nlark-cli version 1.0.96\n")
        )

    def test_capability_probes_cover_the_public_required_set(self):
        runner = CapabilityRunner([0, 0, 0, 0, 0, 0])
        binary = Path("lark-cli")

        report = inspect_capabilities(binary, runner)

        self.assertEqual(REQUIRED_CAPABILITIES, frozenset({
            "help", "schema", "auth_login", "wiki", "docs", "drive",
        }))
        self.assertEqual(report.available, REQUIRED_CAPABILITIES)
        self.assertEqual(report.missing, frozenset())
        self.assertEqual(report.execution_failed, frozenset())
        self.assertFalse(report.cli_unavailable)
        self.assertEqual(runner.calls, [
            [str(binary), "help"],
            [str(binary), "schema"],
            [str(binary), "auth", "login", "--help"],
            [str(binary), "wiki", "--help"],
            [str(binary), "docs", "--help"],
            [str(binary), "drive", "--help"],
        ])

    def test_capability_report_names_missing_commands(self):
        runner = CapabilityRunner([0, 1, 0, 0, 1, 0])

        report = inspect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(report.available, frozenset({"help", "auth_login", "wiki", "drive"}))
        self.assertEqual(report.missing, frozenset({"schema", "docs"}))
        self.assertEqual(report.execution_failed, frozenset())
        self.assertFalse(report.cli_unavailable)

    def test_capability_report_names_probe_execution_failures(self):
        runner = CapabilityRunner([0, OSError("permission denied"), 0, 0, 0, 0])

        report = inspect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(report.available, frozenset({"help", "auth_login", "wiki", "docs", "drive"}))
        self.assertEqual(report.missing, frozenset())
        self.assertEqual(report.execution_failed, frozenset({"schema"}))
        self.assertFalse(report.cli_unavailable)

    def test_capability_report_distinguishes_unavailable_binary(self):
        runner = CapabilityRunner([FileNotFoundError("missing lark-cli")])

        report = inspect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(report.available, frozenset())
        self.assertEqual(report.missing, REQUIRED_CAPABILITIES)
        self.assertEqual(report.execution_failed, frozenset())
        self.assertTrue(report.cli_unavailable)
        self.assertEqual(len(runner.calls), 1)

    def test_detect_capabilities_preserves_frozenset_interface(self):
        runner = CapabilityRunner([0, 0, 0, 0, 0, 0])

        capabilities = detect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(capabilities, REQUIRED_CAPABILITIES)

    def test_capability_report_serializes_sorted_names(self):
        runner = CapabilityRunner([0, 3, 0, 0, OSError("denied"), 0])

        report = inspect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(report.to_dict(), {
            "available": ["auth_login", "drive", "help", "wiki"],
            "missing": ["schema"],
            "execution_failed": ["docs"],
            "cli_unavailable": False,
        })


if __name__ == "__main__":
    unittest.main()
