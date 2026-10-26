"""Read-only setup doctor, owned target initialization, and write acceptance."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from config import ConfigError, load_config
from config_paths import ConfigResolutionError, resolve_config_path
from control_plane import ControlPlane, LockHeld
from lark_cli import LarkCli, redact_sensitive
from lark_cli_context import CliContextError, resolve_cli_context
from lark_cli_contract import REQUIRED_CAPABILITIES
from publisher import NeedsReview, Publisher, TREE_ORDER, WRITE_VERIFICATION_TITLE
from resource_access import authenticated_identity as read_authenticated_identity, check_resource_access
from setup_state import SetupCheck, render_setup_report


WRITE_VERIFICATION_PURPOSE = "write-verification"
WRITE_VERIFICATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _Context:
    config: Any
    config_path: Any
    cli_context: Any
    cli: Any
    publisher: Publisher


class _SetupFailure(RuntimeError):
    def __init__(self, check: SetupCheck) -> None:
        super().__init__(check.message)
        self.check = check


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _profile_from_environment(environ: Mapping[str, str] | None) -> str | None:
    environment = _environment(environ)
    for key in (
        "GENERAL_SCREENWRITER_PROFILE",
        "GENERAL_SCREENWRITER_LARK_PROFILE",
        "LARK_CLI_PROFILE",
    ):
        value = environment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_error(error: Exception) -> str:
    return redact_sensitive(str(error)).strip() or type(error).__name__


def _failure_report(check: SetupCheck) -> dict[str, Any]:
    return render_setup_report((check,))


def _exception_status(error: Exception) -> str:
    message = _safe_error(error).lower()
    if any(token in message for token in (
        "timeout", "timed out", "network", "connection", "dns", "temporar",
    )):
        return "network_blocked"
    if any(token in message for token in ("auth", "login", "credential")):
        return "waiting_admin"
    return "needs_escalation"


def _resolve_context(
    config_path: Any,
    workspace: Any,
    environ: Mapping[str, str] | None,
    runner: Callable[..., Any],
) -> _Context:
    try:
        resolved = resolve_config_path(config_path, workspace, environ)
    except ConfigResolutionError as error:
        status = "config_missing" if error.status == "missing_config" else error.status
        raise _SetupFailure(SetupCheck(
            "config", status, error.status, str(error), (
                "Collect the source and target Wiki links, then generate schema-v2 config.",
            ), "Provide the source and target Wiki links.",
        )) from error
    except Exception as error:
        raise _SetupFailure(SetupCheck(
            "config", "config_invalid", "config_invalid", _safe_error(error),
            ("Regenerate the knowledge configuration from Wiki links.",),
            "Provide valid Wiki links.",
        )) from error

    try:
        config = load_config(resolved.path, resolved.path.parent, environ)
    except ConfigError as error:
        status = "config_invalid"
        raise _SetupFailure(SetupCheck(
            "config", status, getattr(error, "status", status), str(error),
            ("Regenerate the schema-v2 configuration from Wiki links.",),
            "Provide valid source and target Wiki links.",
        )) from error
    except Exception as error:
        raise _SetupFailure(SetupCheck(
            "config", "config_invalid", "config_invalid", _safe_error(error),
            ("Regenerate the schema-v2 configuration from Wiki links.",),
            "Provide valid source and target Wiki links.",
        )) from error

    profile = _profile_from_environment(environ)
    try:
        cli_context = resolve_cli_context(
            profile=profile, environ=environ, runner=runner,
        )
    except CliContextError as error:
        status = {
            "cli_missing": "cli_missing",
            "cli_unavailable": "needs_escalation",
            "unsupported_version": "cli_too_old",
            "version_unparseable": "version_unparseable",
        }.get(error.status, error.status)
        actions = (
            "Find a compatible CLI or install one into the private user runtime.",
        ) if status in {"cli_missing", "cli_too_old"} else (
            "Inspect the CLI installation and rerun doctor.",)
        raise _SetupFailure(SetupCheck(
            "cli", status, error.status, str(error), actions,
            "Resolve the local Lark CLI installation.",
        )) from error
    except Exception as error:
        raise _SetupFailure(SetupCheck(
            "cli", "needs_escalation", "cli_unavailable", _safe_error(error),
            ("Inspect the CLI installation and rerun doctor.",),
            "Resolve the local Lark CLI installation.",
        )) from error

    missing_capabilities = sorted(REQUIRED_CAPABILITIES - set(cli_context.capabilities))
    if missing_capabilities:
        raise _SetupFailure(SetupCheck(
            "cli", "capability_missing", "missing_capabilities",
            "lark-cli is missing required capabilities: " + ", ".join(missing_capabilities),
            ("Inspect the CLI help/schema and use a compatible CLI version.",),
            None,
        ))

    try:
        cli = LarkCli(
            cli_context.binary,
            identity=config.identity,
            runner=runner,
            profile=cli_context.profile,
        )
        publisher = Publisher(
            cli,
            config.target.root_token,
            config.target.space_id,
            root_mode=config.target.root_mode,
        )
    except Exception as error:
        raise _SetupFailure(SetupCheck(
            "runtime", "needs_escalation", "runtime_initialization_failed",
            _safe_error(error), ("Inspect the setup inputs and rerun doctor.",), None,
        )) from error

    return _Context(config, resolved.path, cli_context, cli, publisher)


def _ready_check(check_id: str, message: str) -> SetupCheck:
    return SetupCheck(check_id, "ready", None, message, (), None)


def _inspect_control_tree(publisher: Publisher) -> dict[str, Any]:
    try:
        return publisher.inspect_control_tree()
    except NeedsReview as error:
        return {
            "status": "control_tree_ambiguous",
            "state": "ambiguous",
            "present": [],
            "missing": [],
            "duplicates": [{"reason": _safe_error(error)}],
            "tokens": {},
            "verification_token": None,
        }
    except Exception as error:
        return {
            "status": "network_blocked",
            "state": "unavailable",
            "present": [],
            "missing": [],
            "duplicates": [],
            "tokens": {},
            "verification_token": None,
            "error": _safe_error(error),
        }


def _tree_check(tree: Mapping[str, Any], initializer: bool) -> SetupCheck:
    status = tree.get("status")
    if status == "control_tree_complete":
        return _ready_check("control_tree", "the target control tree is complete")
    if status == "control_tree_ambiguous" or tree.get("state") == "incomplete":
        return SetupCheck(
            "control_tree", "control_tree_ambiguous", "control_tree_ambiguous",
            "the target contains partial or duplicate system pages",
            (
                "Read back the existing system pages and report the conflict.",
                "Do not overwrite, repair, or recreate the existing pages.",
            ),
            "Inspect the target control tree with the resource owner.",
        )
    if status == "network_blocked":
        return SetupCheck(
            "control_tree", "network_blocked", "control_tree_unavailable",
            tree.get("error") or "the target control tree could not be inspected",
            ("Retry the read-only target inspection after connectivity recovers.",),
            None,
        )
    if initializer:
        return SetupCheck(
            "control_tree", "control_tree_missing", "control_tree_missing",
            "the target control tree has not been initialized",
            ("Preview the system page creation, then initialize after confirmation.",),
            None,
        )
    return SetupCheck(
        "control_tree", "waiting_initializer", "control_tree_missing",
        "the empty target must be initialized by the designated maintainer",
        ("Wait for the designated maintainer, then reread the control tree.",),
        "Confirm which maintainer will initialize this shared target.",
    )


def _current_identity(context: _Context) -> tuple[str | None, str | None]:
    try:
        identity = read_authenticated_identity(context.cli)
    except Exception as error:
        return None, _safe_error(error)
    if not identity:
        return None, None
    return identity, None


def _verification_body(profile: str | None, authenticated_identity: str) -> str:
    payload = {
        "authenticated_identity": authenticated_identity,
        "purpose": WRITE_VERIFICATION_PURPOSE,
        "profile": profile or "default",
        "schema_version": WRITE_VERIFICATION_SCHEMA_VERSION,
        "status": "verified",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _verification_is_valid(
    content: str,
    profile: str | None,
    authenticated_identity: str | None,
) -> bool:
    if not authenticated_identity:
        return False
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return False
    return payload == {
        "authenticated_identity": authenticated_identity,
        "purpose": WRITE_VERIFICATION_PURPOSE,
        "profile": profile or "default",
        "schema_version": WRITE_VERIFICATION_SCHEMA_VERSION,
        "status": "verified",
    }


def _read_verification(
    context: _Context,
    tree: Mapping[str, Any] | None = None,
    authenticated_identity: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    try:
        inspection = dict(tree) if tree is not None else dict(
            context.publisher.inspect_control_tree()
        )
    except Exception as error:
        return False, "readback_failed:" + _safe_error(error), dict(tree or {})
    token = inspection.get("verification_token")
    if not token:
        return False, "missing", inspection
    if not authenticated_identity:
        return False, "identity_missing", inspection
    try:
        current = context.publisher.fetch_current(str(token))
        content = current["content"]
    except Exception as error:
        return False, "readback_failed:" + _safe_error(error), inspection
    profile = getattr(context.cli_context, "profile", None)
    if not _verification_is_valid(content, profile, authenticated_identity):
        return False, "marker_mismatch", inspection
    return True, "verified", inspection


def _write_verification_check(
    tree: Mapping[str, Any],
    context: _Context,
    authenticated_identity: str | None,
    identity_error: str | None,
    verification_result: tuple[bool, str, dict[str, Any]] | None = None,
) -> SetupCheck:
    if tree.get("status") != "control_tree_complete":
        return _tree_check(tree, initializer=False)
    if identity_error:
        return SetupCheck(
            "write_verification", "waiting_admin", "identity_unavailable",
            "the authenticated user identity could not be verified",
            ("Recheck user authorization after the authentication error is resolved.",),
            "Resolve the reported user authentication problem.",
        )
    if not authenticated_identity:
        return SetupCheck(
            "write_verification", "needs_escalation", "identity_missing",
            "verified auth status did not expose a stable user identity",
            ("Use a verified user identity that exposes an open ID or user ID.",),
            "Sign in with a user account that exposes a stable user identifier.",
        )
    valid, reason, _ = verification_result or _read_verification(
        context, tree, authenticated_identity,
    )
    if valid:
        return _ready_check("write_verification", "write acceptance was verified")
    uncertain = reason.startswith(("unreadable:", "readback_failed:"))
    message = (
        "write acceptance could not be read back completely"
        if uncertain else
        "write acceptance has not been verified for the current authenticated user"
    )
    return SetupCheck(
        "write_verification",
        "write_result_uncertain" if uncertain else "write_verification_required",
        "write_result_uncertain" if uncertain else None,
        message,
        (
            "Read back the acceptance page before any retry; do not repeat the write blindly.",
        ),
        None,
    )


def _context_ready_checks(context: _Context) -> tuple[SetupCheck, SetupCheck]:
    return (
        _ready_check("cli", "a compatible lark-cli context is ready"),
        _ready_check("config", f"configuration loaded from {context.config_path}"),
    )


def run_doctor(
    config_path=None,
    workspace=None,
    environ=None,
    initializer=False,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Return independent read-only setup checks without loading ControlPlane."""
    try:
        context = _resolve_context(
            config_path, workspace, environ, runner,
        )
    except _SetupFailure as failure:
        return _failure_report(failure.check)

    checks = list(_context_ready_checks(context))
    tree = _inspect_control_tree(context.publisher)
    authenticated_identity, identity_error = _current_identity(context)
    verification_result = None
    if (
        tree.get("status") == "control_tree_complete"
        and authenticated_identity
        and not identity_error
    ):
        verification_result = _read_verification(
            context, tree, authenticated_identity,
        )

    access_payload = None
    try:
        access = check_resource_access(context.config, context.cli)
        access_payload = access.to_dict()
        acceptance_write_proves_target = (
            access.status == "resource_grant_required"
            and context.config.target.root_mode == "space"
            and bool(access.missing)
            and set(access.missing).issubset({"target.create", "target.acceptance_write"})
            and tree.get("status") == "control_tree_complete"
            and bool(verification_result and verification_result[0])
        )
        if acceptance_write_proves_target:
            checks.append(_ready_check(
                "resource_access",
                "the verified acceptance write resolved the read-only target-space create limitation",
            ))
            access_payload["read_only_status"] = access_payload["status"]
            access_payload["read_only_missing"] = access_payload["missing"]
            access_payload["status"] = "ok"
            access_payload["missing"] = []
            access_payload["effective_status"] = "ok"
            access_payload["resolved_by"] = "write_verification"
        elif access.ok:
            checks.append(_ready_check(
                "resource_access", "user identity, source reads, and target checks passed",
            ))
        else:
            checks.append(SetupCheck(
                "resource_access", access.status, access.status,
                "; ".join(access.details) or "resource access is not ready",
                ("Resolve the reported authorization or resource permission gap.",),
                "Grant the reported resource permission." if access.status == "resource_grant_required" else None,
            ))
    except Exception as error:
        checks.append(SetupCheck(
            "resource_access", _exception_status(error), "resource_access_failed",
            _safe_error(error), ("Rerun the read-only resource checks.",), None,
        ))

    checks.append(_tree_check(tree, bool(initializer)))
    if tree.get("status") == "control_tree_complete":
        checks.append(_write_verification_check(
            tree,
            context,
            authenticated_identity,
            identity_error,
            verification_result,
        ))
    report = render_setup_report(tuple(checks))
    if access_payload is not None:
        report["resource_access"] = access_payload
    report["control_tree"] = tree
    return report


def _validate_initialized_documents(context: _Context, tree: Mapping[str, Any]) -> None:
    tokens = tree.get("tokens", {})
    control_plane = ControlPlane(
        context.cli,
        {"index": tokens["index"], "lock": tokens["lock"]},
        lock_ttl_minutes=context.config.lock_ttl_minutes,
    )
    control_plane.read_index()
    _revision, _lock = control_plane.read_lock()


def init_target(
    config_path=None,
    workspace=None,
    environ=None,
    authorized=False,
    initializer_confirmed=False,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Preview and initialize an empty target only for a confirmed maintainer."""
    try:
        context = _resolve_context(
            config_path, workspace, environ, runner,
        )
    except _SetupFailure as failure:
        return _failure_report(failure.check)

    checks = list(_context_ready_checks(context))
    if not initializer_confirmed:
        checks.append(SetupCheck(
            "initialization", "waiting_initializer", "missing_initializer_confirmation",
            "the current user has not confirmed designated initializer ownership",
            ("Ask the designated maintainer to confirm target initialization.",),
            "Confirm that you are the designated maintainer for this target.",
        ))
        return render_setup_report(tuple(checks))
    if not authorized:
        checks.append(SetupCheck(
            "initialization", "needs_escalation", "write_not_authorized",
            "target initialization was not explicitly authorized",
            ("Request explicit approval before creating shared system pages.",),
            "Authorize this one-time target initialization.",
        ))
        return render_setup_report(tuple(checks))

    preview = context.publisher.preview_initialization()
    if preview["status"] == "control_tree_ambiguous":
        report = render_setup_report(tuple(checks + [SetupCheck(
            "initialization", "control_tree_ambiguous", "control_tree_ambiguous",
            "partial or duplicate system pages prevent safe initialization",
            ("Read back the conflict and stop without overwriting it.",),
            "Inspect the target control tree with the resource owner.",
        )]))
        report["preview"] = preview
        return report

    if preview["status"] == "already_initialized":
        tree = preview["control_tree"]
        try:
            _validate_initialized_documents(context, tree)
        except Exception as error:
            report = render_setup_report(tuple(checks + [SetupCheck(
                "initialization", "write_result_uncertain", "initialization_unreadable",
                _safe_error(error), ("Read back the existing control pages before retrying.",), None,
            )]))
            report["preview"] = preview
            report["control_tree"] = tree
            return report
        checks.append(_ready_check(
            "initialization", "the existing target control tree was read back successfully",
        ))
        checks.append(SetupCheck(
            "write_verification", "write_verification_required", None,
            "dedicated write acceptance has not been verified",
            ("Run the dedicated acceptance write and read it back.",), None,
        ))
        report = render_setup_report(tuple(checks))
        report["preview"] = preview
        report["control_tree"] = tree
        return report

    try:
        context.publisher.initialize()
    except Exception as error:
        readback = _inspect_control_tree(context.publisher)
        readback_unavailable = (
            readback.get("status") == "network_blocked"
            or bool(readback.get("error"))
        )
        status = "write_result_uncertain" if (
            readback_unavailable
            or readback.get("present") or readback.get("duplicates")
            or readback.get("misplaced")
            or readback.get("state") == "incomplete"
        ) else _exception_status(error)
        report = render_setup_report(tuple(checks + [SetupCheck(
            "initialization", status,
            "write_result_uncertain" if status == "write_result_uncertain" else "initialization_failed",
            _safe_error(error),
            ("Read back the target before any retry; do not repeat creation blindly.",),
            None,
        )]))
        report["preview"] = preview
        report["readback"] = readback
        return report

    readback = _inspect_control_tree(context.publisher)
    if readback.get("status") != "control_tree_complete":
        report = render_setup_report(tuple(checks + [SetupCheck(
            "initialization", "write_result_uncertain", "initialization_readback_mismatch",
            "system creation did not read back as a complete control tree",
            ("Read back the target before any retry; do not repeat creation blindly.",), None,
        )]))
        report["preview"] = preview
        report["readback"] = readback
        return report

    try:
        _validate_initialized_documents(context, readback)
    except Exception as error:
        report = render_setup_report(tuple(checks + [SetupCheck(
            "initialization", "write_result_uncertain", "initialization_unreadable",
            _safe_error(error), ("Read back the newly created control pages before retrying.",), None,
        )]))
        report["preview"] = preview
        report["readback"] = readback
        return report

    checks.append(_ready_check(
        "initialization", "the system tree was created and read back successfully",
    ))
    checks.append(SetupCheck(
        "write_verification", "write_verification_required", None,
        "dedicated write acceptance has not been verified",
        ("Run the dedicated acceptance write and read it back.",), None,
    ))
    report = render_setup_report(tuple(checks))
    report["preview"] = preview
    report["control_tree"] = readback
    return report


def _verification_write(
    context: _Context,
    tree: Mapping[str, Any],
    authenticated_identity: str,
) -> tuple[bool, str]:
    tokens = tree.get("tokens", {})
    parent_token = tokens.get(TREE_ORDER[-1])
    if not parent_token:
        return False, "missing_system_console"
    profile = getattr(context.cli_context, "profile", None)
    body = _verification_body(profile, authenticated_identity)
    token = tree.get("verification_token")

    if token:
        try:
            current = context.publisher.fetch_current(str(token))
        except Exception as error:
            return False, "readback_failed:" + _safe_error(error)
        try:
            context.cli.update_doc(str(token), current["revision_id"], body)
        except Exception as error:
            valid, reason, _ = _read_verification(
                context, authenticated_identity=authenticated_identity,
            )
            return (True, "verified") if valid else (False, "write_uncertain:" + _safe_error(error))
    else:
        try:
            context.cli.create_doc(str(parent_token), WRITE_VERIFICATION_TITLE, body)
        except Exception as error:
            valid, reason, _ = _read_verification(
                context, authenticated_identity=authenticated_identity,
            )
            return (True, "verified") if valid else (False, "write_uncertain:" + _safe_error(error))

    valid, reason, _ = _read_verification(
        context, authenticated_identity=authenticated_identity,
    )
    return (True, "verified") if valid else (False, "readback_mismatch:" + reason)


def verify_write_access(
    config_path=None,
    workspace=None,
    environ=None,
    authorized=False,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Perform the dedicated acceptance write and read it back before ready."""
    try:
        context = _resolve_context(
            config_path, workspace, environ, runner,
        )
    except _SetupFailure as failure:
        return _failure_report(failure.check)

    checks = list(_context_ready_checks(context))
    tree = _inspect_control_tree(context.publisher)
    if tree.get("status") != "control_tree_complete":
        checks.append(_tree_check(tree, initializer=False))
        report = render_setup_report(tuple(checks))
        report["control_tree"] = tree
        return report
    checks.append(_ready_check("control_tree", "the target control tree is complete"))

    if not authorized:
        checks.append(SetupCheck(
            "write_verification", "needs_escalation", "write_not_authorized",
            "write acceptance was not explicitly authorized",
            ("Request explicit approval before performing the acceptance write.",),
            "Authorize the dedicated acceptance write and readback.",
        ))
        return render_setup_report(tuple(checks))

    authenticated_identity, identity_error = _current_identity(context)
    if identity_error:
        checks.append(SetupCheck(
            "write_verification", "waiting_admin", "identity_unavailable",
            "the authenticated user identity could not be verified",
            ("Resolve the user authentication error, then rerun write verification.",),
            "Resolve the reported user authentication problem.",
        ))
        return render_setup_report(tuple(checks))
    if not authenticated_identity:
        checks.append(SetupCheck(
            "write_verification", "needs_escalation", "identity_missing",
            "verified auth status did not expose a stable user identity",
            ("Use a verified user identity that exposes an open ID or user ID.",),
            "Sign in with a user account that exposes a stable user identifier.",
        ))
        return render_setup_report(tuple(checks))

    tokens = tree["tokens"]
    try:
        control_plane = ControlPlane(
            context.cli,
            {"index": tokens["index"], "lock": tokens["lock"]},
            lock_ttl_minutes=context.config.lock_ttl_minutes,
        )
        lease = control_plane.acquire_lock(
            "setup-write-verify", datetime.now(timezone.utc),
        )
    except LockHeld as error:
        checks.append(SetupCheck(
            "write_verification", "needs_escalation", "lock_held", _safe_error(error),
            ("Wait for the active synchronization lease to expire, then rerun verification.",),
            None,
        ))
        return render_setup_report(tuple(checks))
    except Exception as error:
        checks.append(SetupCheck(
            "write_verification", _exception_status(error), "lock_unavailable",
            _safe_error(error), ("Retry after the remote control plane is available.",), None,
        ))
        return render_setup_report(tuple(checks))

    try:
        success, reason = _verification_write(context, tree, authenticated_identity)
    finally:
        control_plane.release_lock(lease)

    if not success:
        checks.append(SetupCheck(
            "write_verification", "write_result_uncertain", "write_result_uncertain",
            reason, ("Read back the acceptance page and do not blindly retry the write.",), None,
        ))
        return render_setup_report(tuple(checks))

    checks.append(_ready_check(
        "write_verification", "the acceptance page was written and read back successfully",
    ))
    return render_setup_report(tuple(checks))

# Command-level compatibility name for setup CLI consumers.
write_verify = verify_write_access
