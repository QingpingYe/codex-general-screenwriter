import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_bootstrap import default_cli_candidates, ensure_lark_cli
from lark_cli_context import standard_cli_candidates
from lark_runtime import CliInstallResult, RuntimePaths


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


def diagnostics_responses(version, results=(0, 0, 0, 0, 0, 0)):
    capability_results = [
        result if isinstance(result, BaseException) else Completed(returncode=result)
        for result in results
    ]
    return [*cli_responses(version, results), *capability_results]


def diagnostic_commands(binary):
    return [*cli_commands(binary), *cli_commands(binary)[1:]]


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

    def test_default_candidates_delegate_to_the_shared_search_order(self):
        environ = {
            "LARK_CLI_PATH": r"C:\Explicit\lark-cli.exe",
            "APPDATA": r"C:\Users\writer\AppData\Roaming",
            "HOME": r"C:\Users\writer",
        }
        which = lambda name: r"C:\Windows\lark-cli.exe" if name == "lark-cli" else None

        # The bootstrap alias must not keep a second, drifting resolver.
        self.assertEqual(
            default_cli_candidates(environ, which),
            standard_cli_candidates(environ, which),
        )

    def test_existing_supported_cli_is_used_without_install(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        runner = Runner(*diagnostics_responses("1.0.95"))
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result, {
            "status": "available",
            "path": str(binary),
            "version": "1.0.95",
            "installed": False,
            "capability_report": capability_report(),
        })
        self.assertEqual(runner.commands, diagnostic_commands(binary))

    def test_newer_stable_cli_is_supported_without_install(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        runner = Runner(*diagnostics_responses("1.0.100"))
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version"], "1.0.100")
        self.assertEqual(result["capability_report"], capability_report())

    def test_capability_report_is_returned_with_missing_and_failed_probes(self):
        binary = Path(r"C:\Tools\lark-cli.exe")
        results = (0, 1, 0, 0, OSError("denied"), 0)
        runner = Runner(*diagnostics_responses("1.0.95", results))
        result = ensure_lark_cli(candidates=(binary,), runner=runner)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["capability_report"], {
            "available": ["auth_login", "drive", "help", "wiki"],
            "missing": ["schema"],
            "execution_failed": ["docs"],
            "cli_unavailable": False,
        })

    def test_missing_cli_reports_private_npm_install_command(self):
        runner = Runner(FileNotFoundError("lark-cli not found"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            runner=runner,
        )
        command = result["install_command"]
        self.assertEqual(result["status"], "missing")
        self.assertEqual(command[0], "npm")
        self.assertEqual(command[1:3], ["install", "--prefix"])
        self.assertEqual(command[4], "@larksuite/cli@1.0.95")
        self.assertEqual(Path(command[3]).name, "1.0.95")
        self.assertFalse(any("npx" in part.lower() for part in command))
        self.assertNotIn("-g", command)
        self.assertNotIn("skills", command)
        self.assertFalse(runner.commands[1:])

    def test_install_flag_delegates_to_private_runtime_and_rechecks(self):
        candidate = Path(r"C:\Tools\lark-cli.exe")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            installed = root / "1.0.96" / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, installed)
            install_result = CliInstallResult(
                status="installed",
                path=installed,
                version="1.0.96",
                installed=True,
                command=("npm", "install", "--prefix", str(root / "1.0.96"), "@larksuite/cli@1.0.96"),
            )
            runner = Runner(
                Completed("not found", returncode=1),
                *diagnostics_responses("1.0.96"),
            )
            with mock.patch("lark_cli_bootstrap.resolve_runtime_paths", return_value=paths),                     mock.patch("lark_cli_bootstrap.install_private_cli", return_value=install_result) as installer:
                result = ensure_lark_cli(
                    candidates=(candidate,),
                    install=True,
                    runner=runner,
                    environ={},
                )

        self.assertEqual(result["status"], "available")
        self.assertTrue(result["installed"])
        self.assertEqual(result["path"], str(installed.resolve()))
        installer.assert_called_once()
        called_paths, called_version = installer.call_args.args
        self.assertEqual(called_paths, paths)
        self.assertEqual(called_version, "1.0.95")
        self.assertIs(installer.call_args.kwargs["runner"], runner)
        rendered = "\n".join(" ".join(command) for command in runner.commands).lower()
        self.assertNotIn("npx", rendered)
        self.assertNotIn("skills add", rendered)
        self.assertNotIn(" -g", rendered)

    def test_install_failure_is_returned_as_a_distinct_status(self):
        install_result = CliInstallResult(
            status="installation_failed",
            path=None,
            version="1.0.95",
            installed=False,
            command=("npm", "install", "--prefix", r"C:\Private\1.0.95", "@larksuite/cli@1.0.95"),
            reason="npm install failed",
        )
        runner = Runner(Completed("not found", returncode=1))
        with mock.patch("lark_cli_bootstrap.install_private_cli", return_value=install_result):
            result = ensure_lark_cli(
                candidates=(Path(r"C:\Tools\lark-cli.exe"),),
                install=True,
                runner=runner,
                environ={},
            )
        self.assertEqual(result["status"], "installation_failed")
        self.assertFalse(result["installed"])
        self.assertEqual(result["reason"], "npm install failed")
        self.assertEqual(result["install_command"], list(install_result.command))

    def test_unsupported_version_is_not_replaced(self):
        runner = Runner(Completed("lark-cli version 1.0.94\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=False,
            runner=runner,
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["version"], "1.0.94")
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_version_parse_failure_has_a_distinct_state(self):
        runner = Runner(Completed("lark-cli version unknown\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=False,
            runner=runner,
        )
        self.assertEqual(result["status"], "version_unparseable")
        self.assertIsNone(result["version"])
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_prerelease_version_is_version_unparseable(self):
        runner = Runner(Completed("lark-cli version 1.0.95-rc.1\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=False,
            runner=runner,
        )
        self.assertEqual(result["status"], "version_unparseable")
        self.assertIsNone(result["version"])
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_unrelated_node_version_does_not_override_lark_cli_version(self):
        runner = Runner(Completed("Node v22.10.0\nlark-cli version 1.0.94\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=False,
            runner=runner,
        )
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["version"], "1.0.94")

    def test_runtime_version_diagnostic_is_not_a_cli_version(self):
        runner = Runner(Completed("lark-cli requires Node v22.10.0\n"))
        result = ensure_lark_cli(
            candidates=(Path(r"C:\Tools\lark-cli.exe"),),
            install=False,
            runner=runner,
        )
        self.assertEqual(result["status"], "version_unparseable")
        self.assertIsNone(result["version"])
        self.assertEqual(runner.commands, [[r"C:\Tools\lark-cli.exe", "--version"]])

    def test_install_failure_does_not_expose_npm_output_in_bootstrap_contract(self):
        install_result = CliInstallResult(
            status="installation_failed",
            path=None,
            version="1.0.95",
            installed=False,
            command=("npm", "install", "--prefix", r"C:\Private\1.0.95", "@larksuite/cli@1.0.95"),
            reason="npm install failed",
        )
        runner = Runner(Completed("not found", returncode=1))
        with mock.patch("lark_cli_bootstrap.install_private_cli", return_value=install_result):
            result = ensure_lark_cli(
                candidates=(Path(r"C:\Tools\lark-cli.exe"),),
                install=True,
                runner=runner,
                environ={},
            )
        self.assertEqual(result["status"], "installation_failed")
        self.assertNotIn("secret-value", str(result))


if __name__ == "__main__":
    unittest.main()
