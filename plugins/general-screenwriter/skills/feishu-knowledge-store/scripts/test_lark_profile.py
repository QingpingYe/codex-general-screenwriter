import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_context import CliContext
from lark_profile import (
    AppConfigChallenge,
    OrgAppBindingRequired,
    ProfileState,
    begin_app_config,
    ensure_named_profile,
    wait_app_config,
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


class FakePopen:
    def __init__(self, output, returncode=0):
        self.output = output
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        stream = kwargs.get("stdout")
        if stream is not None:
            stream.write(self.output)
            stream.flush()
        return self

    def poll(self):
        return self.returncode


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def context(profile=None):
    return CliContext(
        binary=Path("lark-cli"),
        version="1.0.98",
        profile=profile,
        capabilities=frozenset({"auth_login"}),
    )


class LarkProfileTests(unittest.TestCase):
    def test_existing_named_profile_is_reused_without_creation(self):
        runner = FakeRunner(Completed(json.dumps([
            {"name": "other", "appId": "cli_other"},
            {"name": "team-a", "appId": "cli_team"},
        ])))

        state = ensure_named_profile(context(), "team-a", runner=runner)

        self.assertEqual(state, ProfileState("team-a", "cli_team", "existing"))
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][-2:], ["profile", "list"])
        self.assertFalse(any("config" in call for call in runner.calls))

    def test_missing_per_user_profile_creates_exactly_one_named_app(self):
        runner = FakeRunner(
            Completed(json.dumps([{"name": "other", "appId": "cli_other"}])),
            Completed(
                '{"appId":"cli_created","appSecret":"****","brand":"feishu"}\n',
                "Configuration saved\n",
            ),
        )

        state = ensure_named_profile(context(), "team-a", runner=runner)

        self.assertEqual(state, ProfileState("team-a", "cli_created", "created"))
        self.assertIn(["lark-cli", "config", "init", "--new", "--name", "team-a"], runner.calls)
        creation = next(call for call in runner.calls if "config" in call)
        self.assertNotIn("--force", creation)
        self.assertNotIn("--force-init", creation)
        self.assertNotIn("profile", creation)
        self.assertFalse(any("remove" in call or "rename" in call for call in runner.calls))

    def test_existing_shared_profile_is_bound_without_creation(self):
        runner = FakeRunner(Completed(json.dumps([
            {"name": "org-team", "appId": "cli_org"},
        ])))

        state = ensure_named_profile(
            context("org-team"), "org-team", mode="shared", runner=runner,
        )

        self.assertEqual(state, ProfileState("org-team", "cli_org", "bound"))
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("config", runner.calls[0])

    def test_shared_mode_without_controlled_binding_waits(self):
        runner = FakeRunner(Completed(json.dumps([
            {"name": "personal", "appId": "cli_personal"},
        ])))

        with self.assertRaises(OrgAppBindingRequired) as raised:
            ensure_named_profile(context(), "org-team", mode="shared", runner=runner)

        self.assertEqual(raised.exception.status, "waiting_org_app_binding")
        self.assertEqual(len(runner.calls), 1)

    def test_begin_app_config_preserves_urls_and_uses_private_output_file(self):
        output = (
            "Open this link:\n"
            "  https://open.feishu.cn/page/cli?user_code=AB-12&x=1&next=https%3A%2F%2Fexample.test%2Fa%3Fb%3D1\n"
            "console_url: https://open.feishu.cn/app/cli_new?foo=1&bar=2\n"
        )
        runner = FakePopen(output)

        challenge = begin_app_config(context(), "team-a", runner=runner)

        self.assertIsInstance(challenge, AppConfigChallenge)
        self.assertEqual(challenge.profile_name, "team-a")
        self.assertEqual(
            challenge.verification_url,
            "https://open.feishu.cn/page/cli?user_code=AB-12&x=1&next=https%3A%2F%2Fexample.test%2Fa%3Fb%3D1",
        )
        self.assertEqual(
            challenge.console_url,
            "https://open.feishu.cn/app/cli_new?foo=1&bar=2",
        )
        self.assertEqual(
            runner.calls[0],
            ["lark-cli", "config", "init", "--new", "--name", "team-a"],
        )
        self.assertTrue(challenge.output_path.exists())
        self.assertEqual(challenge.output_path.read_text(encoding="utf-8"), output)
        if os.name != "nt":
            self.assertEqual(challenge.output_path.stat().st_mode & 0o777, 0o600)

    def test_wait_app_config_polls_real_named_profile_state(self):
        challenge = AppConfigChallenge(
            profile_name="team-a",
            verification_url="https://open.feishu.cn/page/cli?user_code=x",
            console_url=None,
            output_path=Path("unused-output.log"),
            context=context(),
        )
        responses = [
            Completed(json.dumps([{"name": "team-a", "appId": ""}])),
            Completed(json.dumps([{"name": "team-a", "appId": "cli_ready"}])),
        ]
        clock = FakeClock()
        with mock.patch("lark_profile.subprocess.run", side_effect=responses) as synced:
            state = wait_app_config(
                challenge,
                timeout_seconds=10,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(state, ProfileState("team-a", "cli_ready", "created"))
        self.assertEqual(synced.call_count, 2)
        first_call = synced.call_args_list[0].args[0]
        self.assertEqual(first_call[:3], ["lark-cli", "--profile", "team-a"])
        self.assertEqual(first_call[-2:], ["profile", "list"])

    def test_wait_app_config_times_out_without_overwriting_profiles(self):
        challenge = AppConfigChallenge(
            profile_name="team-a",
            verification_url="https://open.feishu.cn/page/cli?user_code=x",
            console_url=None,
            output_path=Path("unused-output.log"),
            context=context(),
        )
        calls = []
        clock = FakeClock()

        def profile_list(*args, **kwargs):
            calls.append(args[0])
            return Completed(json.dumps([{"name": "other", "appId": "cli_other"}]))

        with mock.patch("lark_profile.subprocess.run", side_effect=profile_list):
            with self.assertRaises(RuntimeError) as raised:
                wait_app_config(
                    challenge,
                    timeout_seconds=1,
                    clock=clock,
                    sleeper=clock.sleep,
                )

        self.assertEqual(getattr(raised.exception, "status", None), "app_config_timeout")
        self.assertGreaterEqual(len(calls), 1)
        self.assertNotIn("rename", calls[0])


if __name__ == "__main__":
    unittest.main()
