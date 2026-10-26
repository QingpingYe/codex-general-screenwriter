from __future__ import annotations

import hashlib
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lark_runtime import (
    PrivateCliArtifact,
    RuntimePaths,
    install_private_cli,
    resolve_runtime_paths,
)


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class RuntimeRunner:
    """Fake npm/CLI runner that only succeeds when the target file exists."""

    def __init__(self, version="1.0.95", npm_result=None, create_on_install=True):
        self.version = version
        self.npm_result = npm_result or Completed()
        self.create_on_install = create_on_install
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        rendered = [str(part) for part in command]
        self.commands.append(rendered)
        if rendered[1:3] == ["install", "--prefix"]:
            if isinstance(self.npm_result, BaseException):
                raise self.npm_result
            if self.npm_result.returncode == 0 and self.create_on_install:
                prefix = Path(rendered[3])
                target = prefix / "node_modules" / ".bin" / (
                    "lark-cli.cmd" if os.name == "nt" else "lark-cli"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fake cli", encoding="utf-8")
            return self.npm_result

        binary = Path(rendered[0])
        if not binary.exists():
            raise FileNotFoundError(rendered[0])
        if rendered[1:] == ["--version"]:
            return Completed(f"lark-cli version {self.version}\n")
        return Completed()


def current_artifact_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def current_artifact_arch() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x64"


class RuntimePathTests(unittest.TestCase):
    def test_windows_paths_stay_in_user_data_runtime(self):
        environ = {"LOCALAPPDATA": r"C:\Users\writer\AppData\Local"}
        before = dict(environ)

        paths = resolve_runtime_paths(environ=environ, platform="windows")

        self.assertEqual(
            paths.root,
            Path(r"C:\Users\writer\AppData\Local\general-screenwriter\runtimes\lark-cli"),
        )
        self.assertEqual(paths.node_dir, paths.root / "node_modules")
        self.assertEqual(paths.npm_prefix, paths.root)
        self.assertEqual(paths.cli_bin, paths.node_dir / ".bin" / "lark-cli.cmd")
        self.assertTrue(paths.root.is_absolute())
        self.assertEqual(environ, before)

    def test_posix_paths_stay_in_xdg_user_data(self):
        environ = {"HOME": "/home/writer", "XDG_DATA_HOME": "/home/writer/data"}

        paths = resolve_runtime_paths(environ=environ, platform="linux")

        self.assertTrue(
            paths.root.as_posix().endswith(
                "/home/writer/data/general-screenwriter/runtimes/lark-cli"
            )
        )
        self.assertEqual(paths.cli_bin, paths.root / "node_modules" / ".bin" / "lark-cli")


class PrivateCliInstallTests(unittest.TestCase):
    def test_compatible_existing_cli_is_reused_without_npm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            cli_bin.parent.mkdir(parents=True)
            cli_bin.write_text("fake cli", encoding="utf-8")
            paths = RuntimePaths(
                root=root,
                node_dir=root / "node_modules",
                npm_prefix=root,
                cli_bin=cli_bin,
            )
            runner = RuntimeRunner(version="1.0.96")

            with mock.patch("lark_runtime.shutil.which", return_value="npm") as which:
                result = install_private_cli(paths, "1.0.95", runner=runner)

            self.assertEqual(result.status, "available")
            self.assertFalse(result.installed)
            self.assertEqual(result.path, cli_bin.resolve())
            which.assert_not_called()
            self.assertFalse(any(command[1:3] == ["install", "--prefix"] for command in runner.commands))

    def test_compatible_nested_package_binary_is_reused_without_npm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            nested = root / "node_modules" / "@larksuite" / "cli" / "bin" / (
                "lark-cli.exe" if os.name == "nt" else "lark-cli"
            )
            nested.parent.mkdir(parents=True)
            nested.write_text("fake cli", encoding="utf-8")
            paths = RuntimePaths(root, root / "node_modules", root, root / "node_modules" / ".bin" / "missing")
            runner = RuntimeRunner(version="1.0.95")

            with mock.patch("lark_runtime.shutil.which", return_value=None) as which:
                result = install_private_cli(paths, "1.0.95", runner=runner)

            self.assertEqual(result.status, "available")
            self.assertEqual(result.path, nested.resolve())
            which.assert_not_called()

    def test_compatible_sibling_version_is_reused_without_npm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            sibling = root / "1.0.96" / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            sibling.parent.mkdir(parents=True)
            sibling.write_text("fake cli", encoding="utf-8")
            requested = root / "1.0.95" / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, requested)
            runner = RuntimeRunner(version="1.0.96")

            with mock.patch("lark_runtime.shutil.which", return_value=None) as which:
                result = install_private_cli(paths, "1.0.95", runner=runner)

            self.assertEqual(result.status, "available")
            self.assertEqual(result.path, sibling.resolve())
            which.assert_not_called()

    def test_missing_npm_returns_runtime_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            runner = RuntimeRunner()

            with mock.patch("lark_runtime.shutil.which", return_value=None):
                result = install_private_cli(paths, "1.0.95", runner=runner)

            self.assertEqual(result.status, "runtime_missing")
            self.assertFalse(result.installed)
            self.assertTrue(runner.commands)
            self.assertTrue(all(command[1:] == ["--version"] for command in runner.commands))
            self.assertFalse(any(command[1:3] == ["install", "--prefix"] for command in runner.commands))

    def test_npm_resolution_uses_the_injected_environ_path(self):
        seen = []

        def fake_which(name, path=None):
            seen.append((name, path))
            return "npm" if path == r"C:\injected-path" else None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            with mock.patch("lark_runtime.shutil.which", side_effect=fake_which):
                found = install_private_cli(
                    paths, "1.0.95", runner=RuntimeRunner(),
                    environ={"PATH": r"C:\injected-path"},
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            with mock.patch("lark_runtime.shutil.which", side_effect=fake_which):
                missing = install_private_cli(
                    paths, "1.0.95", runner=RuntimeRunner(),
                    environ={"PATH": r"D:\other-path"},
                )

        self.assertEqual(found.status, "installed")
        self.assertEqual(missing.status, "runtime_missing")
        self.assertEqual(seen, [
            ("npm", r"C:\injected-path"),
            ("npm", r"D:\other-path"),
        ])

    def test_npm_install_uses_versioned_private_prefix_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            runner = RuntimeRunner(version="1.0.95")
            npm = r"C:\Node\npm.cmd" if os.name == "nt" else "/usr/bin/npm"

            with mock.patch("lark_runtime.shutil.which", return_value=npm):
                result = install_private_cli(paths, "1.0.95", runner=runner)

            expected_prefix = root / "1.0.95"
            expected_command = [
                npm,
                "install",
                "--prefix",
                str(expected_prefix),
                "@larksuite/cli@1.0.95",
            ]
            install_commands = [
                command for command in runner.commands if command[1:3] == ["install", "--prefix"]
            ]
            self.assertEqual(install_commands, [expected_command])
            self.assertEqual(result.status, "installed")
            self.assertTrue(result.installed)
            self.assertIsNotNone(result.path)
            self.assertTrue(result.path.is_absolute())
            self.assertEqual(result.path, result.path.resolve())
            self.assertIn(expected_prefix.resolve(), result.path.parents)
            rendered = "\n".join(" ".join(command) for command in runner.commands).lower()
            self.assertNotIn(" -g", rendered)
            self.assertNotIn("npx", rendered)
            self.assertNotIn("skills add", rendered)

    def test_npm_failure_returns_installation_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            runner = RuntimeRunner(npm_result=Completed(returncode=1, stderr="download failed"))

            with mock.patch("lark_runtime.shutil.which", return_value="npm"):
                result = install_private_cli(paths, "1.0.95", runner=runner)

            self.assertEqual(result.status, "installation_failed")
            self.assertFalse(result.installed)
            self.assertIn("download failed", result.reason or "")

    def test_artifact_download_failure_has_distinct_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            artifact = PrivateCliArtifact(
                url=(Path(directory) / "missing-artifact").as_uri(),
                sha256="0" * 64,
                platform=current_artifact_platform(),
                arch=current_artifact_arch(),
            )

            result = install_private_cli(
                paths,
                "1.0.95",
                runner=RuntimeRunner(),
                artifact=artifact,
            )

            self.assertEqual(result.status, "download_failed")
            self.assertFalse(result.installed)

    def test_artifact_checksum_failure_has_distinct_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            source = Path(directory) / "artifact.bin"
            source.write_bytes(b"official artifact bytes")
            artifact = PrivateCliArtifact(
                url=source.as_uri(),
                sha256="0" * 64,
                platform=current_artifact_platform(),
                arch=current_artifact_arch(),
            )

            result = install_private_cli(
                paths,
                "1.0.95",
                runner=RuntimeRunner(),
                artifact=artifact,
            )

            self.assertEqual(result.status, "checksum_failed")
            self.assertFalse(result.installed)
            self.assertFalse((root / "1.0.95").exists())

    def test_artifact_checksum_success_installs_private_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            source = Path(directory) / "artifact.bin"
            content = b"official artifact bytes"
            source.write_bytes(content)
            artifact = PrivateCliArtifact(
                url=source.as_uri(),
                sha256=hashlib.sha256(content).hexdigest(),
                platform=current_artifact_platform(),
                arch=current_artifact_arch(),
            )

            result = install_private_cli(
                paths,
                "1.0.95",
                runner=RuntimeRunner(),
                artifact=artifact,
            )

            self.assertEqual(result.status, "installed")
            self.assertIsNotNone(result.path)
            self.assertTrue(result.path.is_absolute())
            self.assertEqual(result.path.read_bytes(), content)
            self.assertIn((root / "1.0.95").resolve(), result.path.parents)

    def test_artifact_runtime_directory_failure_returns_installation_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked_parent = Path(directory) / "blocked"
            blocked_parent.write_text("not a directory", encoding="utf-8")
            root = blocked_parent / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / "lark-cli"
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            source = Path(directory) / "artifact.bin"
            content = b"official artifact bytes"
            source.write_bytes(content)
            artifact = PrivateCliArtifact(
                url=source.as_uri(),
                sha256=hashlib.sha256(content).hexdigest(),
                platform=current_artifact_platform(),
                arch=current_artifact_arch(),
            )

            result = install_private_cli(
                paths,
                "1.0.95",
                runner=RuntimeRunner(),
                artifact=artifact,
            )

            self.assertEqual(result.status, "installation_failed")
            self.assertFalse(result.installed)
            self.assertIn("artifact", result.reason or "")

    def test_artifact_copy_failure_cleans_partial_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / "lark-cli"
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            source = Path(directory) / "artifact.bin"
            content = b"official artifact bytes"
            source.write_bytes(content)
            artifact = PrivateCliArtifact(
                url=source.as_uri(),
                sha256=hashlib.sha256(content).hexdigest(),
                platform=current_artifact_platform(),
                arch=current_artifact_arch(),
            )

            with mock.patch("lark_runtime.shutil.copy2", side_effect=OSError("disk full")):
                result = install_private_cli(
                    paths,
                    "1.0.95",
                    runner=RuntimeRunner(),
                    artifact=artifact,
                )

            self.assertEqual(result.status, "installation_failed")
            self.assertFalse((root / "1.0.95").exists())

    def test_unsupported_artifact_platform_and_arch_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            runner = RuntimeRunner()
            wrong_platform = PrivateCliArtifact(
                url="file:///unused",
                sha256="0" * 64,
                platform="unsupported-os",
                arch=current_artifact_arch(),
            )
            wrong_arch = PrivateCliArtifact(
                url="file:///unused",
                sha256="0" * 64,
                platform=current_artifact_platform(),
                arch="unsupported-arch",
            )

            platform_result = install_private_cli(paths, "1.0.95", runner=runner, artifact=wrong_platform)
            arch_result = install_private_cli(paths, "1.0.95", runner=runner, artifact=wrong_arch)

            self.assertEqual(platform_result.status, "unsupported_platform")
            self.assertEqual(arch_result.status, "unsupported_arch")
            self.assertNotEqual(platform_result.status, arch_result.status)

    def test_artifact_checks_use_runtime_path_platform_and_arch(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = resolve_runtime_paths(
                environ={"LOCALAPPDATA": directory},
                platform="windows",
                arch="arm64",
            )
            self.assertEqual(paths.platform, "windows")
            self.assertEqual(paths.arch, "arm64")
            source = Path(directory) / "artifact.bin"
            content = b"official artifact bytes"
            source.write_bytes(content)
            artifact = PrivateCliArtifact(
                url=source.as_uri(),
                sha256=hashlib.sha256(content).hexdigest(),
                platform="windows",
                arch="arm64",
            )

            result = install_private_cli(
                paths,
                "1.0.95",
                runner=RuntimeRunner(version="1.0.95"),
                artifact=artifact,
            )

            self.assertEqual(result.status, "installed")
            self.assertTrue(result.path.is_absolute())

    def test_successful_install_never_mutates_process_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "lark-cli"
            cli_bin = root / "node_modules" / ".bin" / (
                "lark-cli.cmd" if os.name == "nt" else "lark-cli"
            )
            paths = RuntimePaths(root, root / "node_modules", root, cli_bin)
            before = dict(os.environ)

            with mock.patch("lark_runtime.shutil.which", return_value="npm"):
                result = install_private_cli(paths, "1.0.95", runner=RuntimeRunner())

            self.assertEqual(result.status, "installed")
            self.assertEqual(dict(os.environ), before)
            self.assertEqual(os.environ.get("PATH"), before.get("PATH"))


if __name__ == "__main__":
    unittest.main()
