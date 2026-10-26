import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_contract import (
    MIN_LARK_CLI_VERSION,
    detect_capabilities,
    parse_version,
    version_meets_minimum,
)


class Completed:
    def __init__(self, returncode=0):
        self.stdout = ""
        self.stderr = ""
        self.returncode = returncode


class CapabilityRunner:
    def __init__(self, returncodes):
        self.returncodes = iter(returncodes)
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        return Completed(next(self.returncodes))


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

    def test_parse_version_returns_none_for_unparseable_or_prerelease_text(self):
        self.assertIsNone(parse_version("unparseable"))
        self.assertIsNone(parse_version("1.0.95-rc.1"))

    def test_detect_capabilities_probes_each_required_command(self):
        binary = Path("lark-cli")
        runner = CapabilityRunner([0, 0, 0, 0, 0, 0])

        capabilities = detect_capabilities(binary, runner)

        self.assertEqual(
            capabilities,
            frozenset({"help", "schema", "auth_login", "wiki", "docs", "drive"}),
        )
        self.assertEqual(runner.calls, [
            [str(binary), "help"],
            [str(binary), "schema"],
            [str(binary), "auth", "login", "--help"],
            [str(binary), "wiki", "--help"],
            [str(binary), "docs", "--help"],
            [str(binary), "drive", "--help"],
        ])

    def test_missing_capability_is_reported_by_omission_not_as_an_error(self):
        runner = CapabilityRunner([0, 1, 0, 0, 1, 0])

        capabilities = detect_capabilities(Path("lark-cli"), runner)

        self.assertEqual(capabilities, frozenset({"help", "auth_login", "wiki", "drive"}))


if __name__ == "__main__":
    unittest.main()
