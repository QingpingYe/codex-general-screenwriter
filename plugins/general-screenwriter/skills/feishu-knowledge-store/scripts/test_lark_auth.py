import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_context import CliContext
from lark_auth import (
    DeviceAuthorizationError,
    DeviceAuthorizationExpired,
    REQUIRED_SCOPES,
    begin_device_auth,
    complete_device_auth,
    write_qr_png,
)


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def context(profile="team-a"):
    return CliContext(
        binary=Path("lark-cli"),
        version="1.0.98",
        profile=profile,
        capabilities=frozenset({"auth_login"}),
    )


class LarkAuthTests(unittest.TestCase):
    def test_begin_device_auth_accepts_bare_object_without_user_code(self):
        url = "https://open.feishu.cn/page/cli?user_code=AB-12&x=1&next=https%3A%2F%2Fexample.test%2Fa%3Fb%3D1"
        runner = FakeRunner(Completed(json.dumps({
            "verification_url": url,
            "device_code": "device-secret",
            "expires_in": 600,
        })))

        authorization = begin_device_auth(context(), runner=runner)
        command = runner.calls[0]

        self.assertEqual(authorization.verification_url, url)
        self.assertEqual(authorization.device_code, "device-secret")
        self.assertEqual(authorization.expires_in, 600)
        self.assertEqual(command[:3], ["lark-cli", "--profile", "team-a"])
        self.assertEqual(command[3:5], ["auth", "login"])
        self.assertIn("--no-wait", command)
        self.assertIn("--json", command)
        requested = command[command.index("--scope") + 1]
        for scope in REQUIRED_SCOPES:
            self.assertIn(scope, requested)

    def test_begin_device_auth_accepts_envelope_and_uses_verification_uri_complete(self):
        url = "https://open.feishu.cn/page/cli?user_code=AB-12&keep=1"
        runner = FakeRunner(Completed(json.dumps({
            "ok": True,
            "data": {
                "verification_uri_complete": url,
                "device_code": "device-secret",
                "expires_in": 300,
                "user_code": "AB-12",
            },
        })))

        authorization = begin_device_auth(context(), runner=runner)

        self.assertEqual(authorization.verification_url, url)
        self.assertEqual(authorization.device_code, "device-secret")

    def test_begin_device_auth_requires_device_code_and_expiry(self):
        runner = FakeRunner(Completed(json.dumps({
            "verification_url": "https://example.test/verify",
            "user_code": "AB-12",
            "expires_in": 300,
        })))

        with self.assertRaises(RuntimeError):
            begin_device_auth(context(), runner=runner)

    def test_complete_device_auth_binds_profile_and_drops_authorization_secrets(self):
        runner = FakeRunner(Completed(json.dumps({
            "event": "authorization_complete",
            "user_open_id": "ou_user",
            "user_name": "用户",
            "scope": "docx:document:readonly",
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "device_code": "device-secret",
        })))

        result = complete_device_auth(context(), "device-secret", runner=runner)
        command = runner.calls[0]

        self.assertEqual(result["user_open_id"], "ou_user")
        self.assertNotIn("access-secret", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("refresh-secret", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("device-secret", json.dumps(result, ensure_ascii=False))
        self.assertEqual(command[:3], ["lark-cli", "--profile", "team-a"])
        self.assertEqual(command[3:5], ["auth", "login"])
        self.assertEqual(command[command.index("--device-code") + 1], "device-secret")
        self.assertIn("--json", command)

    def test_complete_device_auth_preserves_structured_warning_without_tokens(self):
        runner = FakeRunner(Completed(json.dumps({
            "event": "authorization_complete",
            "user_open_id": "ou_user",
            "scope": "docx:document:readonly",
            "missing": ["wiki:node:read"],
            "access_token": "access-secret",
        }), returncode=3))

        result = complete_device_auth(context(), "device-secret", runner=runner)

        self.assertEqual(result["missing"], ["wiki:node:read"])
        self.assertNotIn("access-secret", json.dumps(result, ensure_ascii=False))

    def test_write_qr_png_preserves_opaque_url(self):
        url = "https://open.feishu.cn/page/cli?user_code=AB-12&x=1&next=https%3A%2F%2Fexample.test%2Fa%3Fb%3D1"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "auth.png"

            class QRRunner:
                def __call__(self, command, **kwargs):
                    self.command = command
                    Path(command[command.index("--output") + 1]).write_bytes(b"\x89PNG\r\n\x1a\n")
                    return Completed('{"ok":true,"file_path":' + json.dumps(str(destination)) + '}')

            runner = QRRunner()
            result = write_qr_png(context(), url, destination, runner=runner)

            self.assertEqual(result, destination)
            self.assertTrue(destination.exists())
            self.assertEqual(runner.command[3:5], ["auth", "qrcode"])
            self.assertIn(url, runner.command)
            self.assertIn(str(destination), runner.command)

    def test_write_qr_png_rejects_missing_empty_and_invalid_png(self):
        cases = {
            "missing": None,
            "empty": b"",
            "invalid": b"not-a-png",
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in cases.items():
                with self.subTest(name=name):
                    destination = Path(directory) / f"{name}.png"

                    class QRRunner:
                        def __call__(self, command, **kwargs):
                            if payload is not None:
                                Path(command[command.index("--output") + 1]).write_bytes(payload)
                            return Completed('{"ok":true}')

                    with self.assertRaises(DeviceAuthorizationError):
                        write_qr_png(context(), "https://example.test/verify", destination, runner=QRRunner())

    def test_expired_device_authorization_can_restart_with_same_scopes(self):
        scopes = ("scope:one", "scope:two")
        first_runner = FakeRunner(Completed(json.dumps({
            "verification_url": "https://example.test/verify?user_code=one",
            "device_code": "first-device-code",
            "expires_in": 1,
        })))
        first = begin_device_auth(context(), scopes, runner=first_runner)

        expired_runner = FakeRunner(Completed(
            '{"ok":false,"error":{"subtype":"token_expired"}}',
            returncode=1,
        ))
        with self.assertRaises(DeviceAuthorizationExpired) as raised:
            complete_device_auth(
                context(),
                first.device_code,
                runner=expired_runner,
                scopes=first.scopes,
            )
        self.assertEqual(raised.exception.status, "device_code_expired")
        self.assertEqual(raised.exception.scopes, scopes)

        second_runner = FakeRunner(Completed(json.dumps({
            "verification_url": "https://example.test/verify?user_code=two",
            "device_code": "second-device-code",
            "expires_in": 600,
        })))
        second = begin_device_auth(context(), raised.exception.scopes, runner=second_runner)
        self.assertEqual(second.scopes, scopes)
        first_scope = first_runner.calls[0][first_runner.calls[0].index("--scope") + 1]
        second_scope = second_runner.calls[0][second_runner.calls[0].index("--scope") + 1]
        self.assertEqual(first_scope, second_scope)

    def test_complete_error_redacts_exact_device_code_without_key(self):
        runner = FakeRunner(Completed("authorization failed: short-device-code", returncode=1))
        with self.assertRaises(DeviceAuthorizationError) as raised:
            complete_device_auth(context(), "short-device-code", runner=runner)
        self.assertNotIn("short-device-code", str(raised.exception))

    def test_auth_errors_do_not_expose_secrets(self):
        runner = FakeRunner(Completed(
            "failed device_code=device-secret access_token=access-secret refresh_token=refresh-secret",
            returncode=1,
        ))

        with self.assertRaises(RuntimeError) as raised:
            begin_device_auth(context(), runner=runner)

        message = str(raised.exception)
        self.assertNotIn("device-secret", message)
        self.assertNotIn("access-secret", message)
        self.assertNotIn("refresh-secret", message)


if __name__ == "__main__":
    unittest.main()
