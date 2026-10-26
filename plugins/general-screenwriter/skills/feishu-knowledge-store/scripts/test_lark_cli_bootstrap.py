import os
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_bootstrap import BootstrapError, default_cli_candidates, ensure_lark_cli


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class Runner:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.commands = []

    def __call__(self, command, **_kwargs):
        self.commands.append(command)
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        return Completed("", returncode=1, stderr="unexpected command")


CAPABILITY_NAMES = ("help", "schema", "auth_login", "wiki", "docs", "drive")


def cli_responses(version, results=(0, 0, 0, 0, 0, 0)):
    responses = [Completed(f"lark-cli version {version}\n")]
    for result in results:
        responses.append(result if isinstance(result, BaseException) else Completed(returncode=result))
    return responses


def cli_runner(version, results=(0, 0, 0, 0, 0, 0)):
    return Runner(*cli_responses(version, results))


def capability_report(results=(0, 0, 0, 0, 0, 0)):
    available = []
    missing = []
    execution_failed = []
    for name, result in zip(CAPABILITY_NAMES, results):
        if isinstance(result, BaseException):
            execution_failed.append(name)
        elif result == 0:
            available.append(name)
        else:
            missing.append(name)
    return {
        "available": sorted(available),
        "missing": sorted(missing),
        "execution_failed": sorted(execution_failed),
        "cli_unavailable": False,
    }


def cli_commands(binary):
    return [
        [str(binary), "--version"],
        [str(binary), "help"],
        [str(binary), "schema"],
        [str(binary), "auth", "login", "--help"],
        [str(binary), "wiki", "--help"],
        [str(binary), "docs", "--help"],
        [str(binary), "drive", "--help"],
    ]


class LarkCliBootstrapTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows executable locations")
    def test_default_candidates_include_portable_windows_locations(self):
        environ = {
            "LARK_CLI_PATH": r"C:\Explicit\lark-cli.exe",
            "APPDATA": r"C:\Users\writer\AppData\Roaming",
            "ProgramFiles": r"C:\Program Files",
        }
        candidates = default_cli_candidates(
            environ,
            which=lambda name: r"C:\Windows\lark-cli.exe" if name == "lark-cli" else None,
        )
        self.assertEqual(list(candidates), [
            Path(r"C:\Explicit\lark-cli.exe"),
            Path(r"C:\Windows\lark-cli.exe"),
            Path(r"C:\Users\writer\AppData\Roaming\npm\lark-cli.cmd"),
            Path(r"C:\Users\writer\AppData\Roaming\npm\node_modules\@larksuite\cli\bin\lark-cli.exe"),
            Path(r"C:\Program Files\nodejs\lark-cli.cmd"),
        ])

    @unittest.skipIf(os.name == "nt", "POSIX executable locations")
    def test_default_candidates_include_portable_posix_locations(self):
        candidates = default_cli_candidates(
            {"HOME": "/home/writer"}, which=lambda _: None,
        )
        self.assertEqual(candidates, (
            Path("/home/writer/.local/bin/lark-cli"),
            Path("/usr/local/bin/lark-cli"),
            Path("/opt/homebrew/bin/lark-cli"),
        ))

    def test_bootstrap_platform_candidates_exclude_author_drive_letters(self):
        candidates = default_cli_candidates({
            "APPDATA": r"C:\Users\writer\AppData\Roaming",
            "ProgramFiles": r"C:\Program Files",
            "HOME": r"C:\Users\writer",
        }, which=lambda _: None)
        text = "\n".join(str(path) for path in candidates)
        self.assertNotIn("C:\\lark-cli", text)
        self.assertNotIn("D:\\lark-cli", text)

    def test_existing_supported_cli_is_used_without_install(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        runner = cli_runner("1.0.95")
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result, {
            "status": "available",
            "path": str(binary),
            "version": "1.0.95",
            "installed": False,
            "capability_report": capability_report(),
        })
        self.assertEqual(runner.commands, cli_commands(binary))

    def test_newer_stable_cli_is_supported_without_install(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        runner = cli_runner("1.0.100")
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version"], "1.0.100")
        self.assertEqual(result["capability_report"], capability_report())

    def test_capability_report_is_returned_with_missing_and_failed_probes(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        runner = cli_runner("1.0.95", (0, 1, 0, 0, OSError("denied"), 0))
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["capability_report"], {
            "available": ["auth_login", "drive", "help", "wiki"],
            "missing": ["schema"],
            "execution_failed": ["docs"],
            "cli_unavailable": False,
        })

    def test_missing_cli_reports_official_install_command(self):
        runner = Runner(Completed("not found", returncode=1))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            runner=runner,
        )
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["install_command"], ["npx", "@larksuite/cli@latest", "install"])
        self.assertFalse(runner.commands[1:])

    def test_install_flag_runs_installer_and_rechecks(self):
        runner = Runner(
            Completed("not found", returncode=1),
            Completed(""),
            *cli_responses("1.0.96"),
        )
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
        )
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["installed"])
        self.assertEqual(runner.commands[1], ["npx", "@larksuite/cli@latest", "install"])

    def test_install_refreshes_cli_candidates_from_path(self):
        runner = Runner(
            Completed("not found", returncode=1),
            Completed(""),
            *cli_responses("1.0.95"),
        )
        installed_path = Path(r"C:\npm-global\lark-cli.cmd")

        def which(name):
            return str(installed_path) if name == "lark-cli" else None

        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
            environ={},
            which=which,
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["path"], str(installed_path))
        self.assertEqual(runner.commands[2], [str(installed_path), "--version"])

    def test_unsupported_version_is_not_replaced(self):
        runner = Runner(Completed("lark-cli version 1.0.94\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["version"], "1.0.94")
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_version_parse_failure_has_a_distinct_state(self):
        runner = Runner(Completed("lark-cli version unknown\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
        )
        self.assertEqual(result["status"], "version_unparseable")
        self.assertIsNone(result["version"])
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_prerelease_version_is_version_unparseable(self):
        runner = Runner(Completed("lark-cli version 1.0.95-rc.1\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
        )
        self.assertEqual(result["status"], "version_unparseable")
        self.assertIsNone(result["version"])
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_unrelated_node_version_does_not_override_lark_cli_version(self):
        runner = Runner(Completed("Node v22.10.0\nlark-cli version 1.0.94\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=True,
            runner=runner,
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["version"], "1.0.94")

    def test_installer_failure_is_reported_with_redacted_output(self):
        runner = Runner(
            Completed("not found", returncode=1),
            Completed("npm error token=secret-value-123456789012345", returncode=1),
        )
        with self.assertRaises(BootstrapError) as raised:
            ensure_lark_cli(
                candidates=(Path(r"C:\Tools\lark-cli.exe"),),
                install=True,
                runner=runner,
            )
        self.assertIn("lark-cli installer failed", str(raised.exception))
        self.assertNotIn("secret-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
