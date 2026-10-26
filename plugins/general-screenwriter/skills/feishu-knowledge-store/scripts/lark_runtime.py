"""Resolve and install a private user-level Lark CLI runtime."""

from __future__ import annotations

import hashlib
import os
import platform as host_platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.request import urlopen

from lark_cli import LarkCli
from lark_cli_context import CliContextError, resolve_cli_context
from lark_cli_contract import parse_version, version_meets_minimum


@dataclass(frozen=True)
class RuntimePaths:
    """Private runtime locations and their target platform contract."""

    root: Path
    node_dir: Path
    npm_prefix: Path
    cli_bin: Path
    platform: str = ""
    arch: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", _platform_name(self.platform or None))
        object.__setattr__(self, "arch", _architecture_name(self.arch or None))


@dataclass(frozen=True)
class PrivateCliArtifact:
    url: str
    sha256: str
    platform: str
    arch: str


@dataclass(frozen=True)
class CliInstallResult:
    status: str
    path: Path | None
    version: str
    installed: bool
    command: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"available", "installed"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": str(self.path) if self.path is not None else None,
            "version": self.version,
            "installed": self.installed,
            "command": list(self.command),
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def resolve_runtime_paths(
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    arch: str | None = None,
) -> RuntimePaths:
    """Return private paths under the user's data directory.

    The returned prefix is version-neutral. ``install_private_cli`` appends the
    selected stable version before running npm, matching the shared resolver's
    ``runtimes/lark-cli/<version>`` discovery contract.
    """
    environment = os.environ if environ is None else environ
    system = _platform_name(platform)
    architecture = _architecture_name(arch)
    override = (
        environment.get("GENERAL_SCREENWRITER_USER_DATA")
        or environment.get("GENERAL_SCREENWRITER_DATA_DIR")
    )
    if override:
        user_data = Path(override)
    elif system == "windows":
        root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        if root:
            user_data = Path(root)
        else:
            home = environment.get("USERPROFILE") or environment.get("HOME")
            user_data = Path(home) / "AppData" / "Local" if home else Path.home() / "AppData" / "Local"
    else:
        root = environment.get("XDG_DATA_HOME")
        if root:
            user_data = Path(root)
        else:
            home = environment.get("HOME")
            user_data = Path(home) / ".local" / "share" if home else Path.home() / ".local" / "share"

    runtime_root = _absolute(user_data / "general-screenwriter" / "runtimes" / "lark-cli")
    node_dir = runtime_root / "node_modules"
    cli_name = "lark-cli.cmd" if system == "windows" else "lark-cli"
    return RuntimePaths(
        root=runtime_root,
        node_dir=node_dir,
        npm_prefix=runtime_root,
        cli_bin=node_dir / ".bin" / cli_name,
        platform=system,
        arch=architecture,
    )


def install_private_cli(
    paths: RuntimePaths,
    version: str,
    runner: Callable[..., Any] = subprocess.run,
    artifact: PrivateCliArtifact | None = None,
    environ: Mapping[str, str] | None = None,
) -> CliInstallResult:
    """Reuse a compatible private CLI or install one in a versioned prefix.

    The function never mutates PATH and never invokes a global npm install or
    lark skills command. Artifact installation verifies the supplied official
    SHA-256 before copying anything into the private runtime.
    """
    requested = _normalize_requested_version(version)
    if requested is None:
        return CliInstallResult(
            status="unsupported_version",
            path=None,
            version=version,
            installed=False,
            reason="lark-cli version must be a stable version at or above the supported minimum",
        )

    target = _version_paths(paths, requested)
    existing = _reuse_compatible(paths, target, runner)
    if existing is not None:
        return CliInstallResult(
            status="available",
            path=existing.binary,
            version=existing.version,
            installed=False,
        )

    if artifact is not None:
        return _install_artifact(target, requested, runner, artifact)

    npm = _resolve_npm(environ)
    command = _npm_command(paths, requested, npm)
    if npm is None:
        return CliInstallResult(
            status="runtime_missing",
            path=None,
            version=requested,
            installed=False,
            command=tuple(command),
            reason="npm is not available on PATH",
        )
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return CliInstallResult(
            status="runtime_missing",
            path=None,
            version=requested,
            installed=False,
            command=tuple(command),
            reason="npm is not available on PATH",
        )
    except OSError as error:
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=requested,
            installed=False,
            command=tuple(command),
            reason="could not execute npm: " + LarkCli._redact(str(error)),
        )

    if getattr(completed, "returncode", 1) != 0:
        output = " ".join(
            part for part in (
                _text(getattr(completed, "stderr", "")),
                _text(getattr(completed, "stdout", "")),
            ) if part
        )
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=requested,
            installed=False,
            command=tuple(command),
            reason="npm install failed: " + LarkCli._redact(output),
        )

    return _verify_installed(target.cli_bin, requested, runner, tuple(command))


def _resolve_npm(environ: Mapping[str, str] | None) -> str | None:
    """Resolve npm from the injected environment, never from a foreign PATH."""
    if environ is None:
        return shutil.which("npm")
    return shutil.which("npm", path=str(environ.get("PATH") or ""))


def private_install_command(paths: RuntimePaths, version: str) -> tuple[str, ...]:
    """Return the exact user-level npm command without executing it."""
    requested = _normalize_requested_version(version)
    if requested is None:
        requested = version
    return tuple(_npm_command(paths, requested, "npm"))


def _install_artifact(
    target: RuntimePaths,
    version: str,
    runner: Callable[..., Any],
    artifact: PrivateCliArtifact,
) -> CliInstallResult:
    if _platform_name(artifact.platform) != target.platform:
        return CliInstallResult(
            status="unsupported_platform",
            path=None,
            version=version,
            installed=False,
            reason=f"artifact platform {artifact.platform!r} is not supported on {target.platform}",
        )
    if _architecture_name(artifact.arch) != target.arch:
        return CliInstallResult(
            status="unsupported_arch",
            path=None,
            version=version,
            installed=False,
            reason=f"artifact architecture {artifact.arch!r} is not supported on {target.arch}",
        )

    expected = _normalize_sha256(artifact.sha256)
    if expected is None:
        return CliInstallResult(
            status="checksum_failed",
            path=None,
            version=version,
            installed=False,
            reason="official artifact checksum is not a valid SHA-256 value",
        )

    try:
        target.root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=version,
            installed=False,
            reason="artifact runtime directory could not be prepared: " + LarkCli._redact(str(error)),
        )

    download_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="lark-cli-", suffix=".download", dir=target.root, delete=False
        ) as temporary:
            download_path = Path(temporary.name)
            with urlopen(artifact.url, timeout=60) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    temporary.write(chunk)
    except (OSError, URLError, ValueError) as error:
        if download_path is not None:
            _remove_file(download_path)
        _remove_empty_directory(target.root)
        return CliInstallResult(
            status="download_failed",
            path=None,
            version=version,
            installed=False,
            reason="official artifact download failed: " + LarkCli._redact(str(error)),
        )

    binary: Path | None = None
    try:
        actual = _sha256_file(download_path) if download_path is not None else ""
        if actual != expected:
            if download_path is not None:
                _remove_file(download_path)
                download_path = None
            _remove_empty_directory(target.root)
            return CliInstallResult(
                status="checksum_failed",
                path=None,
                version=version,
                installed=False,
                reason="official artifact SHA-256 does not match the supplied checksum",
            )

        binary_name = "lark-cli.exe" if target.platform == "windows" else "lark-cli"
        binary = _absolute(target.root / binary_name)
        binary.parent.mkdir(parents=True, exist_ok=True)
        if download_path is None:
            raise OSError("artifact download produced no file")
        shutil.copy2(download_path, binary)
        if target.platform != "windows":
            binary.chmod(binary.stat().st_mode | 0o111)
    except OSError as error:
        if binary is not None:
            _remove_file(binary)
        if download_path is not None:
            _remove_file(download_path)
            download_path = None
        _remove_empty_directory(target.root)
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=version,
            installed=False,
            reason="could not install verified artifact: " + LarkCli._redact(str(error)),
        )
    finally:
        if download_path is not None:
            _remove_file(download_path)

    result = _verify_installed(binary, version, runner)
    if not result.ok:
        _remove_file(binary)
        _remove_empty_directory(target.root)
    return result


def _reuse_compatible(
    paths: RuntimePaths,
    target: RuntimePaths,
    runner: Callable[..., Any],
):
    candidates = (
        *_private_binary_candidates(target.root, target.platform),
        *_sibling_version_candidates(paths.root, target.platform),
        *_private_binary_candidates(paths.root, target.platform),
        paths.cli_bin,
        target.cli_bin,
    )
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(_absolute(candidate)))
        if key in seen:
            continue
        seen.add(key)
        try:
            context = resolve_cli_context(candidates=(candidate,), runner=runner)
        except CliContextError:
            continue
        return context
    return None


def _sibling_version_candidates(root: Path, platform: str) -> tuple[Path, ...]:
    container = root.parent if parse_version(root.name) is not None else root
    try:
        version_dirs = [
            path for path in container.iterdir()
            if path.is_dir() and parse_version(path.name) is not None
        ]
    except OSError:
        return ()
    version_dirs.sort(
        key=lambda path: (parse_version(path.name) or (0, 0, 0), path.name),
        reverse=True,
    )
    return tuple(
        candidate
        for version_dir in version_dirs
        for candidate in _private_binary_candidates(version_dir, platform)
    )


def _private_binary_candidates(root: Path, platform: str) -> tuple[Path, ...]:
    if platform == "windows":
        return (
            root / "lark-cli.cmd",
            root / "lark-cli.exe",
            root / "node_modules" / ".bin" / "lark-cli.cmd",
            root / "node_modules" / ".bin" / "lark-cli",
            root / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe",
        )
    return (
        root / "lark-cli",
        root / "node_modules" / ".bin" / "lark-cli",
        root / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli",
    )


def _verify_installed(
    binary: Path,
    requested: str,
    runner: Callable[..., Any],
    command: tuple[str, ...] = (),
) -> CliInstallResult:
    try:
        context = resolve_cli_context(candidates=(binary,), runner=runner)
    except CliContextError as error:
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=requested,
            installed=False,
            command=command,
            reason="installed CLI could not be verified: " + str(error),
        )
    if context.version != requested:
        return CliInstallResult(
            status="installation_failed",
            path=None,
            version=requested,
            installed=False,
            command=command,
            reason=f"installed CLI reported {context.version}, expected {requested}",
        )
    return CliInstallResult(
        status="installed",
        path=context.binary,
        version=context.version,
        installed=True,
        command=command,
    )


def _version_paths(paths: RuntimePaths, version: str) -> RuntimePaths:
    prefix = _absolute(paths.npm_prefix)
    if prefix.name != version:
        prefix = _absolute(prefix / version)
    node_dir = prefix / "node_modules"
    cli_name = "lark-cli.cmd" if paths.platform == "windows" else "lark-cli"
    return RuntimePaths(
        root=prefix,
        node_dir=node_dir,
        npm_prefix=prefix,
        cli_bin=node_dir / ".bin" / cli_name,
        platform=paths.platform,
        arch=paths.arch,
    )


def _npm_command(paths: RuntimePaths, version: str, npm: str | None) -> list[str]:
    prefix = _version_paths(paths, version).npm_prefix
    return [
        npm or "npm",
        "install",
        "--prefix",
        str(prefix),
        f"@larksuite/cli@{version}",
    ]


def _normalize_requested_version(version: str) -> str | None:
    parsed = parse_version(version)
    if parsed is None:
        return None
    normalized = ".".join(str(part) for part in parsed)
    return normalized if version_meets_minimum(normalized) else None


def _normalize_sha256(value: str) -> str | None:
    candidate = (value or "").strip().lower()
    if candidate.startswith("sha256:"):
        candidate = candidate[len("sha256:"):]
    if len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
        return None
    return candidate


def _remove_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_empty_directory(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_name(value: str | None = None) -> str:
    raw = (value or sys.platform or "").strip().lower()
    if raw.startswith("win"):
        return "windows"
    if raw in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if raw.startswith("linux"):
        return "linux"
    return raw or "unknown"


def _architecture_name(value: str | None = None) -> str:
    raw = (value or host_platform.machine() or "").strip().lower()
    if raw in {"amd64", "x86_64", "x64"}:
        return "x64"
    if raw in {"arm64", "aarch64"}:
        return "arm64"
    if raw in {"x86", "i386", "i686"}:
        return "x86"
    return raw or "unknown"


def _current_platform() -> str:
    return _platform_name()


def _current_arch() -> str:
    return _architecture_name()


def _absolute(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value or "")


__all__ = [
    "CliInstallResult",
    "PrivateCliArtifact",
    "RuntimePaths",
    "install_private_cli",
    "private_install_command",
    "resolve_runtime_paths",
]
