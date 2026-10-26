"""Resolve one verified Lark CLI executable, version, profile, and capability set."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from config import cli_candidates_from_environment
from lark_cli_contract import detect_capabilities, parse_version, version_meets_minimum


@dataclass(frozen=True)
class CliContext:
    binary: Path
    version: str
    profile: str | None
    capabilities: frozenset[str]


@dataclass(frozen=True)
class CliCandidateFailure:
    path: Path
    reason: str
    status: str
    version: str | None = None


class CliContextError(RuntimeError):
    """Raised when no compatible CLI path can be resolved."""

    def __init__(
        self,
        message: str,
        *,
        status: str = "cli_missing",
        path: Path | None = None,
        reason: str | None = None,
        searched: Sequence[Path] = (),
        failures: Sequence[CliCandidateFailure] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.path = path
        self.reason = reason
        self.searched = tuple(searched)
        self.failures = tuple(failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": str(self),
            "path": str(self.path) if self.path is not None else None,
            "reason": self.reason,
            "searched": [str(path) for path in self.searched],
        }


# Compatibility-friendly alias for consumers that prefer a descriptive name.
CliContextResolutionError = CliContextError

DEFAULT_PROFILE = "general-screenwriter"
PROFILE_ENVIRONMENT_KEYS = (
    "GENERAL_SCREENWRITER_PROFILE",
    "GENERAL_SCREENWRITER_LARK_PROFILE",
    "LARK_CLI_PROFILE",
)


def profile_from_environment(
    environ: Mapping[str, str] | None = None,
    default: str | None = None,
) -> str | None:
    """Return the explicitly bound profile name from the injected environment."""
    environment = os.environ if environ is None else environ
    for key in PROFILE_ENVIRONMENT_KEYS:
        value = environment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def resolve_profile_name(
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    default: str | None = DEFAULT_PROFILE,
) -> str | None:
    """Return the explicit flag, the environment binding, or the shared default.

    Every operational entry point resolves the same named profile so the
    identity that passed setup and write verification is the identity that
    reads sources and publishes targets.
    """
    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    return profile_from_environment(environ, default)


def build_cli_command(context: CliContext, *arguments: str) -> list[str]:
    """Build a command that explicitly binds the context's profile when present."""
    return build_cli_command_for(context.binary, context.profile, *arguments)


def build_cli_command_for(
    binary: Path | str,
    profile: str | None,
    *arguments: str,
) -> list[str]:
    """Internal command builder shared by the context and the subprocess adapter."""
    command = [str(binary)]
    if profile is not None:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return command


def resolve_cli_context(
    candidates: Iterable[Path | str] | None = None,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> CliContext:
    """Return a probe-verified CLI context using explicit-first path resolution.

    When ``candidates`` is supplied it is treated as the complete ordered search
    list.  Otherwise the order is ``LARK_CLI_PATH``, PATH, standard install
    locations, then this plugin's private runtime locations.
    """
    environment = os.environ if environ is None else environ
    selected_profile = _normalize_profile(profile)
    explicit_raw = environment.get("LARK_CLI_PATH")
    explicit = _absolute_path(explicit_raw) if explicit_raw else None

    if candidates is None:
        ordered: list[Path] = list(standard_cli_candidates(environment, which))
        ordered.extend(_private_runtime_candidates(environment))
    else:
        ordered = list(candidates)

    if explicit is not None:
        ordered = [explicit, *ordered]
    ordered = _dedupe_paths(ordered)

    failures: list[CliCandidateFailure] = []
    explicit_key = _path_key(explicit) if explicit is not None else None
    for binary in ordered:
        inspected = _inspect_candidate(binary, selected_profile, runner)
        if isinstance(inspected, CliContext):
            return inspected
        failures.append(inspected)
        if explicit_key is not None and _path_key(binary) == explicit_key:
            raise _error_from_failure(inspected, ordered)

    raise _error_from_failures(failures, ordered)


def _inspect_candidate(
    binary: Path,
    profile: str | None,
    runner: Callable[..., Any],
) -> CliContext | CliCandidateFailure:
    command = build_cli_command_for(binary, profile, "--version")
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
        return CliCandidateFailure(
            binary, "executable not found", "cli_missing",
        )
    except OSError as error:
        return CliCandidateFailure(
            binary, f"could not execute: {error}", "cli_unavailable",
        )

    output = _text(getattr(completed, "stdout", "")) + _text(getattr(completed, "stderr", ""))
    parsed = parse_version(output)
    if parsed is None:
        return_code = getattr(completed, "returncode", 0)
        if return_code != 0:
            reason = f"version command failed with exit code {return_code}"
        else:
            reason = "version output could not be parsed"
        return CliCandidateFailure(binary, reason, "version_unparseable")

    version = ".".join(str(part) for part in parsed)
    if not version_meets_minimum(version):
        return CliCandidateFailure(
            binary,
            f"version {version} is below the supported minimum",
            "unsupported_version",
            version=version,
        )

    capabilities = detect_capabilities(binary, _profile_bound_runner(binary, profile, runner))
    return CliContext(binary, version, profile, capabilities)


def _profile_bound_runner(
    binary: Path,
    profile: str | None,
    runner: Callable[..., Any],
) -> Callable[..., Any]:
    if profile is None:
        return runner

    def bound(command: Sequence[str], **kwargs: Any) -> Any:
        arguments = list(command[1:])
        return runner(build_cli_command_for(binary, profile, *arguments), **kwargs)

    return bound


def _normalize_profile(profile: str | None) -> str | None:
    if profile is None:
        return None
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("profile must be a non-empty string")
    return profile


def standard_cli_candidates(
    environment: Mapping[str, str],
    which: Callable[[str], str | None],
) -> tuple[Path, ...]:
    """Return explicit, PATH-derived, then platform-standard CLI candidates.

    Both ``resolve_cli_context`` and the bootstrap search order use this single
    implementation so probes and diagnostics cannot diverge.
    """
    ordered: list[Path] = []
    for candidate in (environment.get("LARK_CLI_PATH"), which("lark-cli")):
        if not candidate:
            continue
        path = Path(candidate)
        if path not in ordered:
            ordered.append(path)
    ordered.extend(_standard_candidates(environment))
    return tuple(ordered)


def _standard_candidates(environment: Mapping[str, str]) -> tuple[Path, ...]:
    if os.name == "nt":
        candidates: list[Path] = []
        appdata = environment.get("APPDATA")
        if appdata:
            npm_bin = Path(appdata) / "npm"
            candidates.extend((
                npm_bin / "lark-cli.cmd",
                npm_bin / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe",
            ))
        program_files = environment.get("ProgramFiles") or environment.get("PROGRAMFILES")
        if program_files:
            candidates.append(Path(program_files) / "nodejs" / "lark-cli.cmd")
        return tuple(candidates)

    home = environment.get("HOME")
    candidates = []
    if home:
        candidates.append(Path(home) / ".local" / "bin" / "lark-cli")
    candidates.extend((
        Path("/usr/local/bin/lark-cli"),
        Path("/opt/homebrew/bin/lark-cli"),
    ))
    return tuple(candidates)


def _private_runtime_candidates(environment: Mapping[str, str]) -> tuple[Path, ...]:
    root = _user_data_dir(environment) / "general-screenwriter" / "runtimes" / "lark-cli"
    candidates: list[Path] = []
    if root.is_dir():
        version_dirs = sorted(
            (path for path in root.iterdir() if path.is_dir()),
            key=_version_directory_key,
            reverse=True,
        )
        for version_dir in version_dirs:
            candidates.extend(_private_binary_paths(version_dir))
    candidates.extend(_private_binary_paths(root))
    return tuple(candidates)


def _private_binary_paths(root: Path) -> tuple[Path, ...]:
    if os.name == "nt":
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


def _user_data_dir(environment: Mapping[str, str]) -> Path:
    override = (
        environment.get("GENERAL_SCREENWRITER_USER_DATA")
        or environment.get("GENERAL_SCREENWRITER_DATA_DIR")
    )
    if override:
        return Path(override)
    if os.name == "nt":
        root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        if root:
            return Path(root)
        home = environment.get("USERPROFILE") or environment.get("HOME")
        return Path(home) / "AppData" / "Local" if home else Path.home() / "AppData" / "Local"
    root = environment.get("XDG_DATA_HOME")
    if root:
        return Path(root)
    home = environment.get("HOME")
    return Path(home) / ".local" / "share" if home else Path.home() / ".local" / "share"


def _version_directory_key(path: Path) -> tuple[bool, tuple[int, int, int], str]:
    parsed = parse_version(path.name)
    return (parsed is not None, parsed or (0, 0, 0), path.name)


def _dedupe_paths(paths: Iterable[Path | str]) -> list[Path]:
    ordered: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        absolute = _absolute_path(path)
        key = _path_key(absolute)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(absolute)
    return ordered


def _absolute_path(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path).expanduser().absolute()


def _path_key(path: Path | str | None) -> str:
    if path is None:
        return ""
    return os.path.normcase(str(_absolute_path(path)))


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value or "")


def _error_from_failure(
    failure: CliCandidateFailure,
    searched: Sequence[Path],
) -> CliContextError:
    message = f"lark-cli path is unusable: {failure.path} ({failure.reason})"
    return CliContextError(
        message,
        status=failure.status,
        path=failure.path,
        reason=failure.reason,
        searched=searched,
        failures=(failure,),
    )


def _error_from_failures(
    failures: Sequence[CliCandidateFailure],
    searched: Sequence[Path],
) -> CliContextError:
    if not failures:
        return CliContextError(
            "lark-cli executable not found",
            status="cli_missing",
            searched=searched,
        )

    statuses = {failure.status for failure in failures}
    if "unsupported_version" in statuses:
        status = "unsupported_version"
    elif "version_unparseable" in statuses:
        status = "version_unparseable"
    elif "cli_unavailable" in statuses:
        status = "cli_unavailable"
    else:
        status = "cli_missing"

    details = "; ".join(f"{failure.path}: {failure.reason}" for failure in failures)
    first = failures[0]
    return CliContextError(
        f"no compatible lark-cli executable found ({details})",
        status=status,
        path=first.path,
        reason=first.reason,
        searched=searched,
        failures=failures,
    )
