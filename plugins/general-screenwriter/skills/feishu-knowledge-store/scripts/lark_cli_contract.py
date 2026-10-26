"""Lark CLI version and capability contract shared by all consumers."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MIN_LARK_CLI_VERSION = "1.0.95"

_VERSION_TOKEN = (
    r"(?P<version>v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?P<suffix>(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?))"
)
_LARK_CLI_VERSION = re.compile(
    r"(?i)(?<![0-9A-Za-z_-])(?:lark[-_ ]cli|@larksuite/cli)(?![0-9A-Za-z_-])"
    r"[^\r\n0-9]{0,40}?" + _VERSION_TOKEN + r"(?![-0-9A-Za-z_.+])"
)
_BARE_VERSION = re.compile(r"^\s*" + _VERSION_TOKEN + r"\s*$")
_CAPABILITY_PROBES = (
    ("help", ("help",)),
    ("schema", ("schema",)),
    ("auth_login", ("auth", "login", "--help")),
    ("wiki", ("wiki", "--help")),
    ("docs", ("docs", "--help")),
    ("drive", ("drive", "--help")),
)
REQUIRED_CAPABILITIES = frozenset(name for name, _arguments in _CAPABILITY_PROBES)


@dataclass(frozen=True)
class CapabilityReport:
    available: frozenset[str]
    missing: frozenset[str]
    execution_failed: frozenset[str]
    cli_unavailable: bool

    def to_dict(self) -> dict[str, list[str] | bool]:
        return {
            "available": sorted(self.available),
            "missing": sorted(self.missing),
            "execution_failed": sorted(self.execution_failed),
            "cli_unavailable": self.cli_unavailable,
        }


def _stable_version_tuple(version: str) -> tuple[int, int, int] | None:
    match = _BARE_VERSION.fullmatch(version)
    if match is None or match.group("suffix").startswith("-"):
        return None
    components = tuple(match.group(name) for name in ("major", "minor", "patch"))
    if any(len(component) > 1 and component.startswith("0") for component in components):
        return None
    return int(components[0]), int(components[1]), int(components[2])


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse one unambiguous Lark CLI version from command output."""
    source = text or ""
    matches = list(_LARK_CLI_VERSION.finditer(source))
    if matches:
        candidates = {match.group("version").lstrip("vV") for match in matches}
        if len(candidates) != 1:
            return None
        candidate = next(iter(candidates))
    else:
        bare = _BARE_VERSION.fullmatch(source)
        if bare is None:
            return None
        candidate = bare.group("version").lstrip("vV")
    return _stable_version_tuple(candidate)


def version_meets_minimum(version: str) -> bool:
    """Return whether a stable version is at least the supported floor."""
    parsed = parse_version(version)
    minimum = parse_version(MIN_LARK_CLI_VERSION)
    return parsed is not None and minimum is not None and parsed >= minimum


def inspect_capabilities(
    binary: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> CapabilityReport:
    """Return available, missing, and execution-failed capability probes."""
    available: set[str] = set()
    missing: set[str] = set()
    execution_failed: set[str] = set()
    for capability, arguments in _CAPABILITY_PROBES:
        try:
            completed = runner(
                [str(binary), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            return CapabilityReport(
                available=frozenset(available),
                missing=frozenset(REQUIRED_CAPABILITIES - available - execution_failed),
                execution_failed=frozenset(execution_failed),
                cli_unavailable=True,
            )
        except OSError:
            execution_failed.add(capability)
            continue
        if getattr(completed, "returncode", 1) == 0:
            available.add(capability)
        else:
            missing.add(capability)
    return CapabilityReport(
        available=frozenset(available),
        missing=frozenset(missing),
        execution_failed=frozenset(execution_failed),
        cli_unavailable=False,
    )


def detect_capabilities(
    binary: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> frozenset[str]:
    """Return the set of capabilities whose probes succeeded."""
    return inspect_capabilities(binary, runner).available
