#!/usr/bin/env python3
"""Check for a compatible Lark CLI and install it only into user-private paths."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from lark_cli_context import (
    CliContext,
    CliContextError,
    resolve_cli_context,
    standard_cli_candidates,
)
from lark_cli_contract import MIN_LARK_CLI_VERSION, inspect_capabilities
from lark_runtime import (
    CliInstallResult,
    install_private_cli,
    private_install_command,
    resolve_runtime_paths,
)


class BootstrapError(RuntimeError):
    """Compatibility exception for callers that wrap unexpected setup errors."""


def ensure_lark_cli(
    candidates: Iterable[Path | str] | None = None,
    install: bool = False,
    runner: Callable[..., Any] = subprocess.run,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    version: str = MIN_LARK_CLI_VERSION,
) -> dict[str, Any]:
    """Return CLI status, installing only into the user-private runtime.

    An explicit ``LARK_CLI_PATH`` is authoritative: if it is unusable, the
    error is returned without silently installing a different executable.
    """
    environment = os.environ if environ is None else environ
    selected = tuple(candidates) if candidates is not None else None
    try:
        context = resolve_cli_context(
            candidates=selected,
            environ=environment,
            runner=runner,
            which=which,
        )
    except CliContextError as error:
        explicit_failure = _is_explicit_path_failure(error, environment)
        if explicit_failure or not install:
            return _context_error_result(
                error,
                private_install_command(resolve_runtime_paths(environment), version),
            )

        paths = resolve_runtime_paths(environment)
        installation = install_private_cli(
            paths, version, runner=runner, environ=environment,
        )
        if not installation.ok:
            return _installation_result(installation)
        try:
            context = resolve_cli_context(
                candidates=(installation.path,),
                environ=environment,
                runner=runner,
                which=which,
            )
        except CliContextError as recheck_error:
            return _context_error_result(
                recheck_error,
                private_install_command(paths, version),
            )
        return _context_result(context, installed=installation.installed, runner=runner)

    return _context_result(context, installed=False, runner=runner)


def default_cli_candidates(
    environment: Mapping[str, str], which: Callable[[str], str | None]
) -> tuple[Path, ...]:
    """Return the production search candidates for system-visible locations.

    This is a thin alias for the shared resolver so diagnostics can never drift
    from the order production probes; private runtime discovery stays inside
    ``resolve_cli_context`` for the same reason.
    """
    return standard_cli_candidates(environment, which)


def _context_result(
    context: CliContext,
    *,
    installed: bool,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    report = inspect_capabilities(context.binary, runner)
    return {
        "status": "available",
        "path": str(context.binary),
        "version": context.version,
        "installed": installed,
        "capability_report": report.to_dict(),
    }


def _context_error_result(
    error: CliContextError,
    install_command: tuple[str, ...],
) -> dict[str, Any]:
    status = {
        "cli_missing": "missing",
        "unsupported_version": "unsupported",
    }.get(error.status, error.status)
    version = next(
        (failure.version for failure in error.failures if failure.version is not None),
        None,
    )
    result: dict[str, Any] = {
        "status": status,
        "installed": False,
        "install_command": list(install_command),
    }
    if error.path is not None:
        result["path"] = str(error.path)
    if version is not None or error.status == "version_unparseable":
        result["version"] = version
    if error.reason:
        result["reason"] = error.reason
    return result


def _installation_result(result: CliInstallResult) -> dict[str, Any]:
    data = result.to_dict()
    data["install_command"] = data.pop("command")
    return data


def _is_explicit_path_failure(
    error: CliContextError,
    environment: Mapping[str, str],
) -> bool:
    explicit = environment.get("LARK_CLI_PATH")
    if not explicit or error.path is None:
        return False
    return os.path.normcase(str(Path(explicit).expanduser().absolute())) == os.path.normcase(
        str(error.path.expanduser().absolute())
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check and privately install the Feishu Lark CLI")
    parser.add_argument(
        "--install",
        action="store_true",
        help="install a pinned CLI version into the user-private runtime when needed",
    )
    parser.add_argument(
        "--version",
        default=MIN_LARK_CLI_VERSION,
        help="stable lark-cli version to install privately (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)
    result = ensure_lark_cli(install=arguments.install, version=arguments.version)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
