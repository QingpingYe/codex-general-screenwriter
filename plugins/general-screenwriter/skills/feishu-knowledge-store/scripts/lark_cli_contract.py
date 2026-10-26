"""Lark CLI version and capability contract shared by all consumers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable


MIN_LARK_CLI_VERSION = "1.0.95"

_VERSION_TOKEN = re.compile(
    r"(?<![0-9A-Za-z_.+-])v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?P<suffix>(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)"
    r"(?![-0-9A-Za-z_.+])"
)
_CAPABILITY_PROBES = (
    ("help", ("help",)),
    ("schema", ("schema",)),
    ("auth_login", ("auth", "login", "--help")),
    ("wiki", ("wiki", "--help")),
    ("docs", ("docs", "--help")),
    ("drive", ("drive", "--help")),
)


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Parse one stable numeric version from Lark CLI output."""
    match = _VERSION_TOKEN.search(text or "")
    if match is None or match.group("suffix").startswith("-"):
        return None
    components = tuple(match.group(name) for name in ("major", "minor", "patch"))
    if any(len(component) > 1 and component.startswith("0") for component in components):
        return None
    return int(components[0]), int(components[1]), int(components[2])


def version_meets_minimum(version: str) -> bool:
    """Return whether a stable version is at least the supported floor."""
    parsed = parse_version(version)
    minimum = parse_version(MIN_LARK_CLI_VERSION)
    return parsed is not None and minimum is not None and parsed >= minimum


def detect_capabilities(
    binary: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> frozenset[str]:
    """Probe required command surfaces without treating omissions as version errors."""
    detected: set[str] = set()
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
        except (FileNotFoundError, OSError):
            continue
        if getattr(completed, "returncode", 1) == 0:
            detected.add(capability)
    return frozenset(detected)
