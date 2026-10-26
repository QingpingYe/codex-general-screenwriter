import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_cli_context import (
    CliContext,
    CliContextError,
    build_cli_command,
    resolve_cli_context,
)


class Completed:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class Runner:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(list(command))
        return self.responder(command)


def absolute(path):
    return Path(path).resolve()


def responder_for(allowed, version="1.0.95"):
    allowed = {str(absolute(path)) for path in allowed}

    def respond(command):
        if command[0] not in allowed:
            raise FileNotFoundError(command[0])
        if "--version" in command:
            return Completed(f"lark-cli version {version}\n")
        return Completed("", returncode=0)

    return respond


class LarkCliContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_explicit_candidate_precedes_path_and_standard_locations(self):
        explicit = self.root / "explicit" / "lark-cli.exe"
        path_binary = self.root / "path" / "lark-cli.exe"
        runner = Runner(responder_for((explicit, path_binary)))

        context = resolve_cli_context(
            candidates=None,
            environ={"LARK_CLI_PATH": str(explicit)},
            runner=runner,
            which=lambda _: str(path_binary),
        )

        self.assertEqual(context.binary, absolute(explicit))
        self.assertEqual(runner.calls[0][0], str(absolute(explicit)))

    def test_path_candidate_precedes_standard_locations(self):
        path_binary = self.root / "path" / "lark-cli.exe"
        runner = Runner(responder_for((path_binary,)))

        context = resolve_cli_context(
            candidates=None,
            environ={},
            runner=runner,
            which=lambda _: str(path_binary),
        )

        self.assertEqual(context.binary, absolute(path_binary))
        self.assertEqual(runner.calls[0][0], str(absolute(path_binary)))

    @unittest.skipUnless(os.name == "nt", "Windows standard locations")
    def test_standard_directory_is_used_when_path_is_empty(self):
        appdata = self.root / "AppData" / "Roaming"
        standard = appdata / "npm" / "lark-cli.cmd"
        runner = Runner(responder_for((standard,)))

        context = resolve_cli_context(
            candidates=None,
            environ={"APPDATA": str(appdata)},
            runner=runner,
            which=lambda _: None,
        )

        self.assertEqual(context.binary, absolute(standard))
        self.assertEqual(runner.calls[0][0], str(absolute(standard)))

    def test_private_install_directory_is_discovered(self):
        if os.name == "nt":
            data = self.root / "data"
            environ = {"LOCALAPPDATA": str(data)}
            private = (
                data / "general-screenwriter" / "runtimes" / "lark-cli" /
                "1.0.95" / "node_modules" / ".bin" / "lark-cli.cmd"
            )
        else:
            data = self.root / "data"
            environ = {"XDG_DATA_HOME": str(data)}
            private = (
                data / "general-screenwriter" / "runtimes" / "lark-cli" /
                "1.0.95" / "node_modules" / ".bin" / "lark-cli"
            )
        private.parent.mkdir(parents=True)
        private.write_text("", encoding="utf-8")
        runner = Runner(responder_for((private,)))

        context = resolve_cli_context(
            candidates=None,
            environ=environ,
            runner=runner,
            which=lambda _: None,
        )

        self.assertEqual(context.binary, absolute(private))

    def test_first_candidate_may_fail_before_a_later_candidate_succeeds(self):
        bad = self.root / "bad" / "lark-cli.exe"
        good = self.root / "good" / "lark-cli.exe"
        runner = Runner(responder_for((good,)))

        context = resolve_cli_context(
            candidates=(bad, good),
            environ={},
            runner=runner,
        )

        self.assertEqual(context.binary, absolute(good))
        self.assertEqual(runner.calls[0][0], str(absolute(bad)))
        self.assertEqual(runner.calls[1][0], str(absolute(good)))

    def test_invalid_explicit_path_is_reported_and_not_probed_twice(self):
        stale = self.root / "stale" / "lark-cli.exe"

        def deny(_command):
            raise FileNotFoundError(stale)

        runner = Runner(deny)
        with self.assertRaises(CliContextError) as raised:
            resolve_cli_context(
                candidates=None,
                environ={"LARK_CLI_PATH": str(stale)},
                runner=runner,
                which=lambda _: str(stale),
            )

        self.assertEqual(raised.exception.path, absolute(stale))
        self.assertIn("not found", str(raised.exception))
        self.assertEqual(
            [call[0] for call in runner.calls if call[0] == str(absolute(stale))],
            [str(absolute(stale))],
        )

    def test_paths_with_spaces_and_chinese_characters_survive_resolution(self):
        binary = self.root / "工具 目录" / "lark cli 中文.exe"
        runner = Runner(responder_for((binary,)))

        context = resolve_cli_context(
            candidates=(binary,),
            environ={},
            runner=runner,
        )

        self.assertEqual(context.binary, absolute(binary))
        self.assertEqual(runner.calls[0][0], str(absolute(binary)))

    def test_no_profile_means_no_profile_argument(self):
        context = CliContext(
            binary=Path("lark-cli"),
            version="1.0.95",
            profile=None,
            capabilities=frozenset(),
        )
        self.assertEqual(
            build_cli_command(context, "wiki", "--help"),
            ["lark-cli", "wiki", "--help"],
        )

    def test_profile_is_inserted_into_every_probe_and_command(self):
        binary = self.root / "lark-cli.exe"
        runner = Runner(responder_for((binary,)))
        profile = "写作-团队"

        context = resolve_cli_context(
            candidates=(binary,),
            profile=profile,
            environ={},
            runner=runner,
        )

        self.assertEqual(context.profile, profile)
        self.assertEqual(
            build_cli_command(context, "docs", "+fetch", "--doc", "d"),
            [str(absolute(binary)), "--profile", profile, "docs", "+fetch", "--doc", "d"],
        )
        for command in runner.calls:
            self.assertIn("--profile", command)
            self.assertEqual(command[command.index("--profile") + 1], profile)

    def test_capabilities_are_returned_from_the_shared_probe_contract(self):
        binary = self.root / "lark-cli.exe"

        def respond(command):
            if command[0] != str(absolute(binary)):
                raise FileNotFoundError(command[0])
            if "--version" in command:
                return Completed("lark-cli version 1.0.95\n")
            if command[1:3] == ["docs", "--help"]:
                return Completed("", returncode=1)
            return Completed("", returncode=0)

        context = resolve_cli_context(
            candidates=(binary,),
            environ={},
            runner=Runner(respond),
        )

        self.assertNotIn("docs", context.capabilities)
        self.assertIn("wiki", context.capabilities)


if __name__ == "__main__":
    unittest.main()
