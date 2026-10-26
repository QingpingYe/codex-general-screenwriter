#!/usr/bin/env python3
"""Internal JSON setup orchestrator for the first-use Feishu flow.

The AI-facing setup skill calls these commands as implementation details.  The
commands never ask the user to run a terminal command: human involvement is
limited to opening a visible authorization URL/QR code, choosing links, or
approving a write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

SCRIPTS = Path(__file__).resolve().parent
FEISHU_SCRIPTS = SCRIPTS.parents[1] / "feishu-knowledge-store" / "scripts"
if str(FEISHU_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FEISHU_SCRIPTS))

from config import ConfigError, load_config
from config_paths import resolve_config_destination
from knowledge_config_bootstrap import (
    KnowledgeConfigBootstrapError,
    build_config_from_links,
    write_config_atomic,
)
from lark_auth import (
    DeviceAuthorizationError,
    DeviceAuthorizationExpired,
    REQUIRED_SCOPES,
    begin_device_auth,
    complete_device_auth,
    write_qr_png,
)
from lark_cli import LarkCli, redact_sensitive
from lark_cli_bootstrap import ensure_lark_cli
from lark_cli_context import CliContext, CliContextError, resolve_cli_context
from lark_profile import (
    AppConfigRequired,
    OrgAppBindingRequired,
    ProfileError,
    begin_app_config,
    ensure_named_profile,
)
from setup_doctor import DEFAULT_PROFILE, init_target, run_doctor, verify_write_access


COMMANDS = (
    "doctor",
    "auth-start",
    "auth-complete",
    "config-from-links",
    "target-init",
    "write-verify",
)
SETUP_SCHEMA_VERSION = 1
_PROFILE_ENVIRONMENT_KEYS = (
    "GENERAL_SCREENWRITER_PROFILE",
    "GENERAL_SCREENWRITER_LARK_PROFILE",
    "LARK_CLI_PROFILE",
)


class SetupCommandError(RuntimeError):
    """A stable, JSON-serializable internal setup failure."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        reason_code: str | None = None,
        ai_next_actions: Sequence[str] = (),
        human_action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reason_code = reason_code or status
        self.ai_next_actions = tuple(ai_next_actions)
        self.human_action = human_action


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SetupCommandError(
            "invalid_arguments",
            message,
            ai_next_actions=("Use one of the documented internal setup commands.",),
        )


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _safe_error(error: Exception, *secrets: str) -> str:
    message = redact_sensitive(str(error)).strip() or type(error).__name__
    for secret in secrets:
        if isinstance(secret, str) and secret:
            message = message.replace(secret, "[REDACTED]")
    return message


def _report(
    status: str,
    *,
    ready: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SETUP_SCHEMA_VERSION,
        "status": status,
        "ready": bool(ready),
    }
    payload.update(fields)
    return payload


def _error_report(
    error: SetupCommandError,
    *,
    reason_code: str | None = None,
) -> dict[str, Any]:
    return _report(
        error.status,
        reason_code=reason_code or error.reason_code,
        message=str(error),
        ai_next_actions=list(error.ai_next_actions),
        human_action=error.human_action,
    )


def _profile_name(profile: str | None, environ: Mapping[str, str] | None) -> str:
    if isinstance(profile, str) and profile.strip():
        selected = profile.strip()
    else:
        environment = _environment(environ)
        selected = next(
            (
                str(environment.get(key)).strip()
                for key in _PROFILE_ENVIRONMENT_KEYS
                if isinstance(environment.get(key), str)
                and str(environment.get(key)).strip()
            ),
            DEFAULT_PROFILE,
        )
    if any(ord(character) < 32 for character in selected):
        raise SetupCommandError(
            "profile_invalid",
            "profile name must not contain control characters",
            human_action="Choose a normal profile name.",
        )
    return selected


def _normalise_mode(mode: str) -> str:
    value = str(mode or "per_user").strip().lower().replace("-", "_")
    if value in {"per_user", "peruser"}:
        return "per_user"
    if value in {"shared", "org", "organization", "org_app"}:
        return "shared"
    raise SetupCommandError(
        "profile_invalid",
        f"unsupported profile mode: {mode!r}",
    )


def ensure_cli_context(
    *,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> CliContext:
    """Return a compatible CLI context, privately installing only when needed."""
    environment = _environment(environ)
    try:
        return resolve_cli_context(
            profile=profile,
            environ=environment,
            runner=runner,
            which=which,
        )
    except CliContextError as first_error:
        if environment.get("LARK_CLI_PATH"):
            raise SetupCommandError(
                first_error.status,
                _safe_error(first_error),
                ai_next_actions=("Fix the explicit lark-cli path or remove it.",),
                human_action="Resolve the configured lark-cli path.",
            ) from first_error

    installation = ensure_lark_cli(
        install=True,
        runner=runner,
        environ=environment,
        which=which,
    )
    if installation.get("status") != "available":
        raise SetupCommandError(
            str(installation.get("status") or "cli_missing"),
            redact_sensitive(str(installation.get("reason") or "the private lark-cli runtime is unavailable")),
            ai_next_actions=("Resolve the private runtime installation before retrying setup.",),
            human_action="Allow the local runtime installation or resolve the reported environment blocker.",
        )
    path = installation.get("path")
    if not path:
        raise SetupCommandError("cli_missing", "private installation did not return a CLI path")
    try:
        return resolve_cli_context(
            candidates=(path,),
            profile=profile,
            environ=environment,
            runner=runner,
            which=which,
        )
    except CliContextError as error:
        raise SetupCommandError(
            error.status,
            _safe_error(error),
            ai_next_actions=("Inspect the private CLI installation and retry setup.",),
            human_action="Resolve the local lark-cli installation problem.",
        ) from error


def qr_destination(profile: str, stage: str) -> Path:
    """Return a durable-enough, non-secret QR path for the visible challenge."""
    safe_profile = re.sub(r"[^A-Za-z0-9._-]+", "-", profile).strip("-") or "profile"
    safe_stage = re.sub(r"[^A-Za-z0-9._-]+", "-", stage).strip("-") or "setup"
    root = Path(tempfile.gettempdir()) / "general-screenwriter" / "setup-qr"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe_profile}-{safe_stage}-{uuid.uuid4().hex}.png"


def _visible_qr(
    context: CliContext,
    url: str,
    profile: str,
    stage: str,
    runner: Callable[..., Any],
) -> tuple[str | None, str | None]:
    destination = qr_destination(profile, stage)
    try:
        write_qr_png(context, url, destination, runner=runner)
    except Exception as error:
        return None, _safe_error(error)
    return str(destination), None


def doctor_report(
    *,
    config_path: str | None = None,
    workspace: str | None = None,
    environ: Mapping[str, str] | None = None,
    initializer: bool = False,
    profile: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    environment = _environment(environ)
    return run_doctor(
        config_path=config_path,
        workspace=workspace,
        environ=environment,
        initializer=initializer,
        profile=_profile_name(profile, environment),
        runner=runner,
    )


# Command-level compatibility name for internal callers.
doctor = doctor_report

def auth_start(
    *,
    profile: str | None = None,
    mode: str = "per_user",
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    environment = _environment(environ)
    selected_profile = _profile_name(profile, environment)
    selected_mode = _normalise_mode(mode)
    try:
        context = ensure_cli_context(
            profile=selected_profile,
            environ=environment,
            runner=runner,
            which=which,
        )
    except SetupCommandError as error:
        return _error_report(error)

    try:
        ensure_named_profile(
            context,
            selected_profile,
            mode=selected_mode,
            runner=runner,
        )
    except AppConfigRequired:
        if selected_mode == "shared":
            return _report(
                "waiting_org_app_binding",
                profile=selected_profile,
                ai_next_actions=("Use an existing organisation-approved local profile binding.",),
                human_action="Ask the organisation owner to provide the approved local app binding.",
            )
        try:
            challenge = begin_app_config(context, selected_profile, runner=popen)
        except ProfileError as error:
            return _error_report(
                SetupCommandError(
                    error.status,
                    _safe_error(error),
                    ai_next_actions=("Resolve the application configuration state and retry.",),
                    human_action="Complete the visible application setup step if prompted.",
                ),
            )
        except Exception as error:
            return _error_report(
                SetupCommandError(
                    "app_config_failed",
                    _safe_error(error),
                    ai_next_actions=("Retry the application configuration flow.",),
                    human_action="Complete the visible application setup step if prompted.",
                ),
            )
        qr_path, qr_error = _visible_qr(
            context, challenge.verification_url, selected_profile, "app-config", runner,
        )
        return _report(
            "waiting_user",
            stage="app_config",
            profile=selected_profile,
            verification_url=challenge.verification_url,
            console_url=challenge.console_url,
            qr_path=qr_path,
            qr_error=qr_error,
            ai_next_actions=("After the user completes app creation, reread the real profile state.",),
            human_action="Open the application setup link and complete the visible Feishu approval.",
        )
    except OrgAppBindingRequired as error:
        return _report(
            "waiting_org_app_binding",
            profile=selected_profile,
            reason_code=error.status,
            message=_safe_error(error),
            ai_next_actions=("Use an existing organisation-approved local profile binding.",),
            human_action="Ask the organisation owner to provide the approved local app binding.",
        )
    except ProfileError as error:
        return _error_report(
            SetupCommandError(
                error.status,
                _safe_error(error),
                ai_next_actions=("Resolve the named profile state and retry.",),
                human_action="Complete the visible account selection if prompted.",
            ),
        )
    except SetupCommandError as error:
        return _error_report(error)

    try:
        authorization = begin_device_auth(context, runner=runner)
    except DeviceAuthorizationExpired as error:
        return _report(
            "device_code_expired",
            profile=selected_profile,
            scopes=list(error.scopes),
            message=_safe_error(error),
            ai_next_actions=("Start a new device authorization with the same scopes.",),
            human_action="Open the new authorization link when it appears.",
        )
    except DeviceAuthorizationError as error:
        return _report(
            error.status,
            profile=selected_profile,
            message=_safe_error(error),
            ai_next_actions=("Recheck the CLI authentication capability and retry.",),
            human_action=None,
        )
    except Exception as error:
        return _report(
            "device_auth_failed",
            profile=selected_profile,
            message=_safe_error(error),
            ai_next_actions=("Recheck the CLI authentication capability and retry.",),
            human_action=None,
        )

    qr_path, qr_error = _visible_qr(
        context, authorization.verification_url, selected_profile, "device-auth", runner,
    )
    return _report(
        "waiting_user",
        stage="device_auth",
        profile=selected_profile,
        verification_url=authorization.verification_url,
        qr_path=qr_path,
        qr_error=qr_error,
        expires_in=authorization.expires_in,
        scopes=list(authorization.scopes or REQUIRED_SCOPES),
        device_code=authorization.device_code,
        ai_next_actions=(
            "Keep the device code only in the active setup session and resume after the user completes consent.",
            "After completion, reread the authenticated user state.",
        ),
        human_action="Open the authorization link or scan the QR code, then approve the requested Feishu access.",
    )


def auth_complete(
    *,
    device_code: str,
    profile: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    if not isinstance(device_code, str) or not device_code.strip():
        return _error_report(SetupCommandError(
            "device_code_missing",
            "device code is required",
            human_action="Restart the authorization flow to obtain a fresh device code.",
        ))
    environment = _environment(environ)
    selected_profile = _profile_name(profile, environment)
    try:
        context = ensure_cli_context(
            profile=selected_profile,
            environ=environment,
            runner=runner,
            which=which,
        )
        payload = complete_device_auth(context, device_code.strip(), runner=runner)
    except DeviceAuthorizationExpired as error:
        return _report(
            "device_code_expired",
            profile=selected_profile,
            scopes=list(error.scopes),
            message=_safe_error(error, device_code),
            ai_next_actions=("Start a fresh authorization request with the same scopes.",),
            human_action="Open the new authorization link when it appears.",
        )
    except (DeviceAuthorizationError, SetupCommandError) as error:
        status = getattr(error, "status", "device_auth_failed")
        return _error_report(SetupCommandError(
            status,
            _safe_error(error, device_code),
            ai_next_actions=("Reread authorization state before retrying.",),
            human_action="Complete the visible Feishu authorization if it is still pending.",
        ))
    except Exception as error:
        return _error_report(SetupCommandError(
            "device_auth_failed",
            _safe_error(error, device_code),
            ai_next_actions=("Reread authorization state before retrying.",),
            human_action=None,
        ))

    sanitized = _sanitize_payload(payload)
    missing_scopes = sanitized.get("missing") if isinstance(sanitized, dict) else None
    if isinstance(missing_scopes, list) and missing_scopes:
        return _report(
            "waiting_admin",
            reason_code="missing_scopes",
            profile=selected_profile,
            missing_scopes=missing_scopes,
            authorization=sanitized,
            ai_next_actions=("Resolve the missing application scopes, then reread the real authorization state.",),
            human_action="Ask the application or organisation owner to grant the missing scopes.",
        )
    return _report(
        "authorized",
        profile=selected_profile,
        authorization=sanitized,
        ai_next_actions=("Ask for the source and target Wiki links if no valid config exists.",),
        human_action=None,
    )


def config_from_links(
    *,
    source_url: str,
    target_url: str,
    profile: str | None = None,
    config_path: str | None = None,
    workspace: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    environment = _environment(environ)
    selected_profile = _profile_name(profile, environment)
    try:
        context = ensure_cli_context(
            profile=selected_profile,
            environ=environment,
            runner=runner,
            which=which,
        )
        destination = resolve_config_destination(
            config_path,
            workspace,
            environment,
        )
    except SetupCommandError as error:
        return _error_report(error)
    except Exception as error:
        return _error_report(SetupCommandError(
            "config_invalid",
            _safe_error(error),
            ai_next_actions=("Resolve the configuration destination and retry.",),
            human_action="Choose a writable local configuration location.",
        ))

    if destination.is_file():
        try:
            load_config(destination, destination.parent, environment)
        except (ConfigError, OSError, ValueError):
            pass
        else:
            return _report(
                "config_exists",
                config_path=str(destination),
                profile=selected_profile,
                ai_next_actions=("Run the read-only setup doctor against the existing configuration.",),
                human_action=None,
            )

    try:
        cli = LarkCli(
            context.binary,
            identity="user",
            runner=runner,
            profile=context.profile,
        )
        config = build_config_from_links(source_url, target_url, cli)
        written = write_config_atomic(config, destination)
    except KnowledgeConfigBootstrapError as error:
        return _error_report(SetupCommandError(
            error.status,
            _safe_error(error),
            ai_next_actions=("Ask only for missing or corrected source and target Wiki links.",),
            human_action="Provide two distinct, accessible Feishu Wiki links.",
        ))
    except Exception as error:
        return _error_report(SetupCommandError(
            "config_invalid",
            _safe_error(error),
            ai_next_actions=("Reread the links and authorization state, then retry.",),
            human_action="Provide valid source and target Wiki links.",
        ))

    return _report(
        "configured",
        config_path=str(written),
        profile=selected_profile,
        ai_next_actions=("Run the read-only setup doctor and resource checks next.",),
        human_action=None,
    )


def target_init(
    *,
    initializer: bool = False,
    authorized: bool = False,
    profile: str | None = None,
    config_path: str | None = None,
    workspace: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    environment = _environment(environ)
    return init_target(
        config_path=config_path,
        workspace=workspace,
        environ=environment,
        authorized=authorized,
        initializer_confirmed=initializer,
        profile=_profile_name(profile, environment),
        runner=runner,
    )


def write_verify(
    *,
    authorized: bool = False,
    profile: str | None = None,
    config_path: str | None = None,
    workspace: str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    environment = _environment(environ)
    return verify_write_access(
        config_path=config_path,
        workspace=workspace,
        environ=environment,
        authorized=authorized,
        profile=_profile_name(profile, environment),
        runner=runner,
    )


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_payload(nested)
            for key, nested in value.items()
            if str(key).lower().replace("-", "").replace("_", "")
            not in {"devicecode", "usercode", "accesstoken", "refreshtoken", "authorization", "bearer", "token"}
        }
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def _add_common(parser: argparse.ArgumentParser, *, include_mode: bool = False) -> None:
    parser.add_argument("--config")
    parser.add_argument("--workspace")
    parser.add_argument("--profile")
    if include_mode:
        parser.add_argument("--mode", default="per_user")
    parser.add_argument("--json", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(prog="setup_cli.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor")
    _add_common(doctor)
    doctor.add_argument("--initializer", action="store_true")

    auth_start_parser = subparsers.add_parser("auth-start")
    _add_common(auth_start_parser, include_mode=True)

    auth_complete_parser = subparsers.add_parser("auth-complete")
    _add_common(auth_complete_parser)
    auth_complete_parser.add_argument("--device-code", required=True)

    config_parser = subparsers.add_parser("config-from-links")
    _add_common(config_parser)
    config_parser.add_argument("--source-url", required=True)
    config_parser.add_argument("--target-url", required=True)

    target_init_parser = subparsers.add_parser("target-init")
    _add_common(target_init_parser)
    target_init_parser.add_argument("--initializer", action="store_true")
    target_init_parser.add_argument("--authorized", action="store_true")

    write_verify_parser = subparsers.add_parser("write-verify")
    _add_common(write_verify_parser)
    write_verify_parser.add_argument("--authorized", action="store_true")
    return parser


def _exit_code(command: str, payload: Mapping[str, Any]) -> int:
    status = payload.get("status")
    if command == "doctor":
        return 0 if payload.get("ready") else 1
    if command == "auth-start":
        return 0 if status == "waiting_user" and payload.get("verification_url") else 1
    if command == "auth-complete":
        return 0 if status == "authorized" else 1
    if command == "config-from-links":
        return 0 if status in {"configured", "config_exists"} else 1
    if command == "target-init":
        if payload.get("ready"):
            return 0
        checks = payload.get("checks")
        if isinstance(checks, list):
            if any(
                isinstance(check, Mapping)
                and check.get("check_id") == "initialization"
                and check.get("status") == "ready"
                for check in checks
            ):
                return 0
        return 1
    if command == "write-verify":
        return 0 if payload.get("ready") else 1
    return 1


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments and not arguments[0].startswith("-") and arguments[0] not in COMMANDS:
            raise SetupCommandError("invalid_command", f"unsupported command: {arguments[0]}")
        parsed = _parser().parse_args(arguments)
        command = parsed.command
        if command == "doctor":
            payload = doctor_report(
                config_path=parsed.config,
                workspace=parsed.workspace,
                environ=environ,
                initializer=parsed.initializer,
                profile=parsed.profile,
                runner=runner,
            )
        elif command == "auth-start":
            payload = auth_start(
                profile=parsed.profile,
                mode=parsed.mode,
                environ=environ,
                runner=runner,
                popen=popen,
                which=which,
            )
        elif command == "auth-complete":
            payload = auth_complete(
                device_code=parsed.device_code,
                profile=parsed.profile,
                environ=environ,
                runner=runner,
                which=which,
            )
        elif command == "config-from-links":
            payload = config_from_links(
                source_url=parsed.source_url,
                target_url=parsed.target_url,
                profile=parsed.profile,
                config_path=parsed.config,
                workspace=parsed.workspace,
                environ=environ,
                runner=runner,
                which=which,
            )
        elif command == "target-init":
            payload = target_init(
                initializer=parsed.initializer,
                authorized=parsed.authorized,
                profile=parsed.profile,
                config_path=parsed.config,
                workspace=parsed.workspace,
                environ=environ,
                runner=runner,
            )
        elif command == "write-verify":
            payload = write_verify(
                authorized=parsed.authorized,
                profile=parsed.profile,
                config_path=parsed.config,
                workspace=parsed.workspace,
                environ=environ,
                runner=runner,
            )
        else:  # pragma: no cover - argparse owns the command set.
            raise SetupCommandError("invalid_command", f"unsupported command: {command}")
    except SetupCommandError as error:
        payload = _error_report(error)
        payload["allowed_commands"] = list(COMMANDS)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2 if error.status in {"invalid_arguments", "invalid_command"} else 1
    except Exception as error:
        payload = _error_report(SetupCommandError("setup_failed", _safe_error(error)))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return _exit_code(command, payload)


if __name__ == "__main__":
    raise SystemExit(main())
