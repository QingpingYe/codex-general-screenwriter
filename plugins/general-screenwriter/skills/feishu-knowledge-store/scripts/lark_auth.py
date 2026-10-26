"""Device authorization and QR generation for the Lark CLI.

Only the session object returned by ``begin_device_auth`` carries the short-lived
device code.  It is never written to plugin state or included in diagnostics.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from lark_cli import redact_sensitive
from lark_cli_context import CliContext, build_cli_command


REQUIRED_SCOPES: tuple[str, ...] = (
    "docx:document:create",
    "docx:document:readonly",
    "docx:document:write_only",
    "wiki:node:retrieve",
    "wiki:node:create",
    "wiki:node:read",
    "wiki:space:read",
    "drive:file:download",
    "docs:permission.member:auth",
)

_SENSITIVE_PAYLOAD_KEYS = {
    "appsecret",
    "clientsecret",
    "accesstoken",
    "refreshToken".lower(),
    "devicecode",
    "usercode",
    "authorization",
    "bearer",
    "token",
}


class LarkAuthError(RuntimeError):
    """Base class for device authorization failures."""

    status = "auth_failed"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "error": str(self)}


class DeviceAuthorizationError(LarkAuthError):
    status = "device_auth_failed"


class DeviceAuthorizationExpired(DeviceAuthorizationError):
    status = "device_code_expired"

    def __init__(self, message: str, *, scopes: Sequence[str] = REQUIRED_SCOPES) -> None:
        super().__init__(message)
        self.scopes = tuple(scopes)


@dataclass(frozen=True)
class DeviceAuthorization:
    verification_url: str
    device_code: str = field(repr=False)
    expires_in: int
    scopes: tuple[str, ...] = field(default=(), repr=False, compare=False)


def begin_device_auth(
    context: CliContext,
    scopes: Sequence[str] = REQUIRED_SCOPES,
    runner: Callable[..., Any] = subprocess.run,
) -> DeviceAuthorization:
    """Start split-flow device authorization without waiting."""
    _require_profile(context)
    scope_list = _normalise_scopes(scopes)
    scope_value = " ".join(scope_list)
    args = ("auth", "login", "--scope", scope_value, "--no-wait", "--json")
    completed, stdout, stderr = _run_sync(context, args, runner)
    payload = _command_payload(completed, stdout, stderr, operation="device authorization")

    verification_url = _string_field(
        payload,
        ("verification_url", "verification_uri_complete", "verification_uri"),
    )
    device_code = _string_field(payload, ("device_code", "deviceCode"))
    expires_in = _int_field(payload, ("expires_in", "expire_in"))

    if verification_url is None or device_code is None or expires_in is None:
        raise DeviceAuthorizationError(
            "device authorization response is missing verification_url, "
            "device_code, or expires_in"
        )
    return DeviceAuthorization(
        verification_url=verification_url,
        device_code=device_code,
        expires_in=expires_in,
        scopes=tuple(scope_list),
    )


def complete_device_auth(
    context: CliContext,
    device_code: str,
    runner: Callable[..., Any] = subprocess.run,
    *,
    scopes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Resume a previously started split-flow authorization.

    ``scopes`` must be the original ``DeviceAuthorization.scopes`` when the
    caller is retrying after expiry; otherwise a custom authorization would
    silently fall back to the core scope set.
    """
    _require_profile(context)
    if not isinstance(device_code, str) or not device_code.strip():
        raise ValueError("device_code must be a non-empty string")
    selected_scopes = _normalise_scopes(
        REQUIRED_SCOPES if scopes is None else scopes
    )

    args = ("auth", "login", "--device-code", device_code, "--json")
    completed, stdout, stderr = _run_sync(context, args, runner)
    try:
        payload = _command_payload(
            completed,
            stdout,
            stderr,
            operation="device authorization completion",
            secret_values=(device_code,),
        )
    except DeviceAuthorizationExpired as error:
        raise DeviceAuthorizationExpired(
            str(error), scopes=selected_scopes
        ) from error
    if not isinstance(payload, dict):
        raise DeviceAuthorizationError("device authorization completion returned no JSON object")
    return _sanitize_payload(payload)


def write_qr_png(
    context: CliContext,
    url: str,
    destination: str | Path,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    """Write the official PNG QR code while preserving the URL byte-for-byte."""
    _require_profile(context)
    if not isinstance(url, str) or not url:
        raise ValueError("url must be a non-empty string")
    target = Path(destination)
    completed, stdout, stderr = _run_sync(
        context,
        ("auth", "qrcode", url, "--output", str(target)),
        runner,
    )
    if getattr(completed, "returncode", 0) != 0:
        raise DeviceAuthorizationError(
            "lark-cli auth qrcode failed: "
            + redact_sensitive(_diagnostic(stdout, stderr))
        )
    payload = _select_json_payload(stdout, "device authorization")
    if payload is not None and _is_error_payload(payload):
        _raise_command_error("qr code generation", stdout, stderr, payload)
    _verify_png(target)
    return target


def _verify_png(path: Path) -> None:
    signature = b"\x89PNG\r\n\x1a\n"
    try:
        valid = path.is_file() and path.stat().st_size > 0
        if valid:
            with path.open("rb") as stream:
                valid = stream.read(len(signature)) == signature
    except OSError:
        valid = False
    if not valid:
        raise DeviceAuthorizationError(
            "lark-cli auth qrcode did not produce a valid non-empty PNG"
        )


def _require_profile(context: CliContext) -> None:
    if not getattr(context, "profile", None):
        raise DeviceAuthorizationError(
            "a named CLI profile must be bound before device authorization"
        )


def _run_sync(
    context: CliContext,
    arguments: Sequence[str],
    runner: Callable[..., Any],
) -> tuple[Any, str, str]:
    command = build_cli_command(context, *arguments)
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as error:
        raise DeviceAuthorizationError(
            f"lark-cli executable unavailable: {context.binary}"
        ) from error
    except OSError as error:
        raise DeviceAuthorizationError(
            "could not execute lark-cli: " + redact_sensitive(str(error))
        ) from error
    return completed, _text(getattr(completed, "stdout", "")), _text(getattr(completed, "stderr", ""))


def _command_payload(
    completed: Any,
    stdout: str,
    stderr: str,
    *,
    operation: str,
    secret_values: Sequence[str] = (),
) -> Any:
    payload = _select_json_payload(stdout, operation)
    if getattr(completed, "returncode", 0) != 0 and not _is_success_payload(payload):
        _raise_command_error(operation, stdout, stderr, payload, secret_values=secret_values)
    if payload is None:
        raise DeviceAuthorizationError(f"{operation} returned no JSON payload")
    if _is_error_payload(payload):
        _raise_command_error(
            operation,
            stdout,
            stderr,
            payload,
            secret_values=secret_values,
        )
    return _unwrap_payload(payload)


def _raise_command_error(
    operation: str,
    stdout: str,
    stderr: str,
    payload: Any = None,
    *,
    secret_values: Sequence[str] = (),
) -> None:
    serialized = json.dumps(payload, ensure_ascii=False) if payload is not None else ""
    diagnostic = _redact_values(
        redact_sensitive(_diagnostic(stdout, stderr, serialized)),
        secret_values,
    )
    lowered = diagnostic.lower()
    message = f"{operation} failed"
    if diagnostic:
        message += f": {diagnostic}"
    if any(term in lowered for term in ("expired", "invalid_grant", "invalid grant")):
        raise DeviceAuthorizationExpired(message)
    raise DeviceAuthorizationError(message)


def _redact_values(text: str, values: Sequence[str]) -> str:
    for value in sorted(
        {value for value in values if isinstance(value, str) and value},
        key=len,
        reverse=True,
    ):
        text = text.replace(value, "[REDACTED]")
    return text


def _normalise_scopes(scopes: Sequence[str]) -> list[str]:
    if isinstance(scopes, str):
        raw = scopes.replace(",", " ").split()
    else:
        try:
            raw = list(scopes)
        except TypeError as error:
            raise ValueError("scopes must be a sequence of strings") from error
    result: list[str] = []
    seen: set[str] = set()
    for scope in raw:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scopes must contain only non-empty strings")
        value = scope.strip()
        if value not in seen:
            seen.add(value)
            result.append(value)
    if not result:
        raise ValueError("scopes must not be empty")
    return result


def _select_json_payload(text: str, operation: str) -> Any:
    values = [value for value in _iter_json(text) if isinstance(value, dict)]
    if not values:
        return None
    if "completion" in operation:
        preferred = ("event", "user_open_id", "user_name", "scope")
    else:
        preferred = (
            "verification_url",
            "verification_uri_complete",
            "verification_uri",
            "device_code",
        )
    for value in reversed(values):
        if _find_key(value, preferred) is not None:
            return value
    return values[-1]


def _iter_json(text: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        yield value


def _unwrap_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("ok") is True and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _is_success_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is True:
        return True
    if payload.get("event") == "authorization_complete":
        return True
    data = payload.get("data")
    return isinstance(data, dict) and data.get("event") == "authorization_complete"


def _is_error_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("ok") is False:
        return True
    if payload.get("error"):
        return True
    code = payload.get("code")
    return code not in (None, 0, "0")


def _string_field(payload: Any, keys: Sequence[str]) -> str | None:
    value = _find_key(payload, keys)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_field(payload: Any, keys: Sequence[str]) -> int | None:
    value = _find_key(payload, keys)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _find_key(value: Any, keys: Sequence[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for nested in value.values():
            found = _find_key(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_key(item, keys)
            if found is not None:
                return found
    return None


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if _normalise_key(key) in _SENSITIVE_PAYLOAD_KEYS:
                continue
            result[key] = _sanitize_payload(nested)
        return result
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_payload(item) for item in value)
    return value


def _normalise_key(key: Any) -> str:
    return "".join(char for char in str(key).lower() if char not in "-_ ")


def _diagnostic(stdout: str, stderr: str, extra: str = "") -> str:
    return " ".join(part.strip() for part in (stdout, stderr, extra) if part and part.strip())


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
