import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS = Path(__file__).parent
FEISHU_SCRIPTS = SCRIPTS.parents[1] / "feishu-knowledge-store" / "scripts"
for location in (SCRIPTS, FEISHU_SCRIPTS):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))

from lark_auth import DeviceAuthorization
from lark_cli_context import CliContext
from lark_cli_contract import REQUIRED_CAPABILITIES
from lark_profile import ProfileState

import setup_cli


def context(profile="general-screenwriter"):
    return CliContext(
        binary=Path(sys.executable),
        version="1.0.98",
        profile=profile,
        capabilities=frozenset(REQUIRED_CAPABILITIES),
    )


class SetupCliTests(unittest.TestCase):
    def run_main(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            code = setup_cli.main(arguments)
        return code, json.loads(output.getvalue())

    def test_doctor_outputs_json_and_ready_exit_code(self):
        report = {
            "schema_version": 1,
            "status": "ready",
            "ready": True,
            "blocking_checks": [],
            "checks": [],
            "ai_next_actions": [],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "run_doctor", return_value=report) as doctor:
            code, payload = self.run_main(["doctor", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload, report)
        self.assertTrue(doctor.call_args.kwargs["initializer"] is False)

    def test_doctor_non_ready_outputs_json_and_nonzero_exit(self):
        report = {
            "schema_version": 1,
            "status": "cli_missing",
            "ready": False,
            "blocking_checks": ["cli"],
            "checks": [],
            "ai_next_actions": ["install privately"],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "run_doctor", return_value=report):
            code, payload = self.run_main(["doctor", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "cli_missing")

    def test_explicit_profile_is_forwarded_to_every_profile_bound_phase(self):
        report = {
            "schema_version": 1,
            "status": "ready",
            "ready": True,
            "blocking_checks": [],
            "checks": [],
            "ai_next_actions": [],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "run_doctor", return_value=report) as doctor:
            self.run_main(["doctor", "--profile", "team-z", "--json"])
        with mock.patch.object(setup_cli, "init_target", return_value=report) as init:
            self.run_main([
                "target-init", "--profile", "team-z",
                "--initializer", "--authorized", "--json",
            ])
        with mock.patch.object(setup_cli, "verify_write_access", return_value=report) as verify:
            self.run_main(["write-verify", "--profile", "team-z", "--authorized", "--json"])

        self.assertEqual(doctor.call_args.kwargs["profile"], "team-z")
        self.assertEqual(init.call_args.kwargs["profile"], "team-z")
        self.assertEqual(verify.call_args.kwargs["profile"], "team-z")
    def test_default_profile_is_continuous_across_profile_bound_phases(self):
        report = {
            "schema_version": 1,
            "status": "ready",
            "ready": True,
            "blocking_checks": [],
            "checks": [],
            "ai_next_actions": [],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "run_doctor", return_value=report) as doctor:
            self.run_main(["doctor", "--json"])
        with mock.patch.object(setup_cli, "init_target", return_value=report) as init:
            self.run_main(["target-init", "--initializer", "--authorized", "--json"])
        with mock.patch.object(setup_cli, "verify_write_access", return_value=report) as verify:
            self.run_main(["write-verify", "--authorized", "--json"])

        self.assertEqual(doctor.call_args.kwargs["profile"], "general-screenwriter")
        self.assertEqual(init.call_args.kwargs["profile"], "general-screenwriter")
        self.assertEqual(verify.call_args.kwargs["profile"], "general-screenwriter")
    def test_auth_start_returns_visible_challenge_without_leaking_code_into_guidance(self):
        authorization = DeviceAuthorization(
            verification_url="https://open.feishu.cn/page/cli?user_code=AB-12",
            device_code="device-secret",
            expires_in=600,
        )
        qr_path = Path(tempfile.gettempdir()) / "general-screenwriter-auth-start.png"

        def write_qr(_context, _url, destination, runner=None):
            Path(destination).write_bytes(b"\x89PNG\r\n\x1a\n")
            return Path(destination)

        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(
                setup_cli,
                "ensure_named_profile",
                return_value=ProfileState("general-screenwriter", "cli_app", "existing"),
            ),
            mock.patch.object(setup_cli, "begin_device_auth", return_value=authorization),
            mock.patch.object(setup_cli, "write_qr_png", side_effect=write_qr),
            mock.patch.object(setup_cli, "qr_destination", return_value=qr_path),
        ):
            code, payload = self.run_main(["auth-start", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "waiting_user")
        self.assertEqual(payload["stage"], "device_auth")
        self.assertEqual(payload["verification_url"], authorization.verification_url)
        self.assertEqual(payload["device_code"], "device-secret")
        self.assertNotIn("device-secret", payload["human_action"])
        self.assertNotIn("device-secret", " ".join(payload["ai_next_actions"]))
        self.assertTrue(qr_path.exists())
        qr_path.unlink(missing_ok=True)

    def test_auth_start_missing_profile_returns_app_configuration_challenge(self):
        challenge = SimpleNamespace(
            profile_name="general-screenwriter",
            verification_url="https://open.feishu.cn/app-register?x=1",
            console_url="https://open.feishu.cn/console/app",
        )
        qr_path = Path(tempfile.gettempdir()) / "general-screenwriter-app-config.png"

        def write_qr(_context, _url, destination, runner=None):
            Path(destination).write_bytes(b"\x89PNG\r\n\x1a\n")
            return Path(destination)

        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(setup_cli, "ensure_named_profile", side_effect=setup_cli.AppConfigRequired("general-screenwriter")),
            mock.patch.object(setup_cli, "begin_app_config", return_value=challenge),
            mock.patch.object(setup_cli, "write_qr_png", side_effect=write_qr),
            mock.patch.object(setup_cli, "qr_destination", return_value=qr_path),
        ):
            code, payload = self.run_main(["auth-start", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "app_config")
        self.assertEqual(payload["verification_url"], challenge.verification_url)
        self.assertEqual(payload["console_url"], challenge.console_url)
        self.assertNotIn("device_code", payload)
        self.assertTrue(qr_path.exists())
        qr_path.unlink(missing_ok=True)

    def test_listed_unconfigured_profile_resumes_app_configuration(self):
        challenge = SimpleNamespace(
            profile_name="general-screenwriter",
            verification_url="https://open.feishu.cn/app-register?x=1",
            console_url=None,
        )

        class Completed:
            returncode = 0
            stderr = ""

            def __init__(self, stdout):
                self.stdout = stdout

        def runner(command, **_kwargs):
            if list(command)[-2:] == ["profile", "list"]:
                return Completed(json.dumps([
                    {"name": "general-screenwriter", "appId": ""},
                ]))
            raise AssertionError(f"unexpected command: {command}")

        output = io.StringIO()
        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(setup_cli, "begin_app_config", return_value=challenge) as begin,
            mock.patch.object(setup_cli, "write_qr_png", return_value=None),
            mock.patch.object(
                setup_cli, "qr_destination",
                return_value=Path(tempfile.gettempdir()) / "unused-qr.png",
            ),
            redirect_stdout(output),
        ):
            code = setup_cli.main(["auth-start", "--json"], runner=runner)

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "app_config")
        self.assertEqual(payload["status"], "waiting_user")
        self.assertNotIn("device_code", payload)
        self.assertTrue(begin.called)

    def test_auth_complete_outputs_json_and_redacts_device_code(self):
        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(
                setup_cli,
                "complete_device_auth",
                return_value={"event": "authorization_complete", "user_open_id": "ou_user"},
            ),
        ):
            code, payload = self.run_main([
                "auth-complete", "--device-code", "device-secret", "--json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "authorized")
        self.assertNotIn("device-secret", json.dumps(payload))

    def test_auth_complete_reports_missing_scopes_as_waiting_admin(self):
        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(
                setup_cli,
                "complete_device_auth",
                return_value={
                    "event": "authorization_complete",
                    "user_open_id": "ou_user",
                    "missing": ["wiki:node:read"],
                },
            ),
        ):
            code, payload = self.run_main([
                "auth-complete", "--device-code", "device-secret", "--json",
            ])

        self.assertEqual(code, 1)
        self.assertEqual(payload["status"], "waiting_admin")
        self.assertEqual(payload["missing_scopes"], ["wiki:node:read"])
    def test_config_from_links_writes_json_result(self):
        destination = Path(tempfile.gettempdir()) / "general-screenwriter-config-test.json"
        destination.unlink(missing_ok=True)
        config = object()
        with (
            mock.patch.object(setup_cli, "ensure_cli_context", return_value=context()),
            mock.patch.object(setup_cli, "resolve_config_destination", return_value=destination),
            mock.patch.object(setup_cli, "LarkCli", return_value=object()),
            mock.patch.object(setup_cli, "build_config_from_links", return_value=config),
            mock.patch.object(setup_cli, "write_config_atomic", return_value=destination) as write,
        ):
            code, payload = self.run_main([
                "config-from-links",
                "--source-url", "https://example.feishu.cn/wiki/source",
                "--target-url", "https://example.feishu.cn/wiki/target",
                "--json",
            ])

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "configured")
        self.assertEqual(payload["config_path"], str(destination))
        write.assert_called_once_with(config, destination)

    def test_target_init_and_write_verify_return_structured_reports(self):
        init_report = {
            "schema_version": 1,
            "status": "write_verification_required",
            "ready": False,
            "blocking_checks": ["write_verification"],
            "checks": [{"check_id": "initialization", "status": "ready"}],
            "ai_next_actions": ["verify writes"],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "init_target", return_value=init_report) as init:
            init_code, init_payload = self.run_main([
                "target-init", "--initializer", "--authorized", "--json",
            ])

        verify_report = dict(init_report, status="ready", ready=True, blocking_checks=[])
        with mock.patch.object(setup_cli, "verify_write_access", return_value=verify_report):
            verify_code, verify_payload = self.run_main(["write-verify", "--authorized", "--json"])

        self.assertEqual(init_code, 0)
        self.assertEqual(init_payload["status"], "write_verification_required")
        self.assertTrue(init.call_args.kwargs["initializer_confirmed"])
        self.assertTrue(init.call_args.kwargs["authorized"])
        self.assertEqual(verify_code, 0)
        self.assertTrue(verify_payload["ready"])

    def test_qr_challenge_files_are_owner_only_and_cleared_when_ready(self):
        root = Path(tempfile.gettempdir()) / "general-screenwriter" / "setup-qr"
        root.mkdir(parents=True, exist_ok=True)
        stale = root / "team-qr-device-auth-stale.png"
        stale.write_bytes(b"\x89PNG\r\n\x1a\n")

        destination = setup_cli.qr_destination("team-qr", "device-auth")
        destination.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertTrue(destination.parent == root)
        self.assertTrue(destination.name.startswith("team-qr-device-auth-"))
        if os.name != "nt":
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

        other = root / "other-profile-device-auth.png"
        other.write_bytes(b"\x89PNG\r\n\x1a\n")

        report = {
            "schema_version": 1, "status": "ready", "ready": True,
            "blocking_checks": [], "checks": [], "ai_next_actions": [],
            "human_action": None,
        }
        with mock.patch.object(setup_cli, "verify_write_access", return_value=report):
            code, payload = self.run_main([
                "write-verify", "--authorized", "--profile", "team-qr", "--json",
            ])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ready"])
        self.assertFalse(destination.exists())
        self.assertFalse(stale.exists())
        # Another profile's challenge is untouched.
        self.assertTrue(other.exists())
        other.unlink(missing_ok=True)

    def test_unknown_command_returns_json_and_usage_exit(self):
        code, payload = self.run_main(["not-a-command", "--json"])

        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "invalid_command")
        self.assertIn("doctor", payload["allowed_commands"])
        self.assertNotIn("store", payload["allowed_commands"])


class LauncherTests(unittest.TestCase):
    def _probe_script(self, directory):
        path = Path(directory) / "probe.py"
        path.write_text(
            "import json, os, sys\n"
            "print(json.dumps({'executable': sys.executable, 'path': os.environ.get('PATH', '')}))\n",
            encoding="utf-8",
        )
        return path

    def _powershell(self):
        return shutil.which("pwsh") or shutil.which("powershell")

    def _run_powershell(self, script, probe, environment):
        command = [
            self._powershell(), "-NoProfile", "-NonInteractive",
            "-File", str(SCRIPTS / "runtime_launcher.ps1"),
            "-Script", str(probe),
        ]
        return subprocess.run(command, capture_output=True, text=True, env=environment, check=False)

    def _run_shell(self, probe, environment):
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("bash is unavailable")
        command = [bash, str(SCRIPTS / "runtime_launcher.sh"), probe.as_posix()]
        return subprocess.run(command, capture_output=True, text=True, env=environment, check=False)

    def test_powershell_launcher_uses_host_system_user_priority(self):
        powershell = self._powershell()
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        missing = str(Path(tempfile.gettempdir()) / "missing-python-for-setup-test.exe")
        cases = ("host", "system", "user")
        with tempfile.TemporaryDirectory() as directory:
            probe = self._probe_script(directory)
            for preferred in cases:
                with self.subTest(preferred=preferred):
                    environment = os.environ.copy()
                    environment["GENERAL_SCREENWRITER_HOST_PYTHON"] = sys.executable if preferred == "host" else missing
                    environment["GENERAL_SCREENWRITER_SYSTEM_PYTHON"] = sys.executable if preferred == "system" else missing
                    environment["GENERAL_SCREENWRITER_USER_PYTHON"] = sys.executable if preferred == "user" else missing
                    result = self._run_powershell(powershell, probe, environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(Path(payload["executable"]).resolve(), Path(sys.executable).resolve())

    def test_shell_launcher_uses_host_system_user_priority(self):
        missing = str(Path(tempfile.gettempdir()) / "missing-python-for-setup-test")
        with tempfile.TemporaryDirectory() as directory:
            probe = self._probe_script(directory)
            for preferred in ("host", "system", "user"):
                with self.subTest(preferred=preferred):
                    environment = os.environ.copy()
                    environment["GENERAL_SCREENWRITER_HOST_PYTHON"] = sys.executable if preferred == "host" else missing
                    environment["GENERAL_SCREENWRITER_SYSTEM_PYTHON"] = sys.executable if preferred == "system" else missing
                    environment["GENERAL_SCREENWRITER_USER_PYTHON"] = sys.executable if preferred == "user" else missing
                    result = self._run_shell(probe, environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertEqual(Path(payload["executable"]).resolve(), Path(sys.executable).resolve())

    def test_launchers_return_runtime_missing_without_an_interpreter(self):
        missing = str(Path(tempfile.gettempdir()) / "missing-python-for-setup-test")
        with tempfile.TemporaryDirectory() as directory:
            probe = self._probe_script(directory)
            environment = os.environ.copy()
            environment["PATH"] = ""
            environment["GENERAL_SCREENWRITER_HOST_PYTHON"] = missing
            environment["GENERAL_SCREENWRITER_SYSTEM_PYTHON"] = missing
            environment["GENERAL_SCREENWRITER_USER_PYTHON"] = missing
            environment["USERPROFILE"] = ""
            environment["LOCALAPPDATA"] = ""
            if self._powershell():
                result = self._run_powershell(self._powershell(), probe, environment)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["status"], "runtime_missing")
            if shutil.which("bash"):
                result = self._run_shell(probe, environment)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)["status"], "runtime_missing")

    def test_launchers_do_not_mutate_path(self):
        marker = "setup-launcher-path-marker"
        with tempfile.TemporaryDirectory() as directory:
            probe = self._probe_script(directory)
            environment = os.environ.copy()
            environment["PATH"] = marker
            environment["GENERAL_SCREENWRITER_HOST_PYTHON"] = sys.executable
            if self._powershell():
                result = self._run_powershell(self._powershell(), probe, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(marker, json.loads(result.stdout)["path"])
            if shutil.which("bash"):
                result = self._run_shell(probe, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(marker, json.loads(result.stdout)["path"])

        powershell_text = (SCRIPTS / "runtime_launcher.ps1").read_text(encoding="utf-8")
        shell_text = (SCRIPTS / "runtime_launcher.sh").read_text(encoding="utf-8")
        self.assertNotIn("$env:PATH =", powershell_text)
        self.assertNotIn("$env:PATH=", powershell_text)
        self.assertNotIn("export PATH", shell_text)
        for text in (powershell_text, shell_text):
            self.assertNotIn("npx", text)
            self.assertNotIn("skills add", text)


if __name__ == "__main__":
    unittest.main()
