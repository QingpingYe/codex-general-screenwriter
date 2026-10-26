"""Named Lark profiles and the two-phase application configuration flow."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Sequence

from lark_cli import redact_sensitive
from lark_cli_context import CliContext, CliContextError, build_cli_command, resolve_cli_context


ProfileSource = Literal["existing", "created", "bound"]
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


@dataclass(frozen=True)
class ProfileState:
    name: str
    app_id: str
    source: ProfileSource


class ProfileError(RuntimeError):
    """Base class for profile/app-configuration failures."""

    status = "profile_error"

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "error": str(self)}


class OrgAppBindingRequired(ProfileError):
    """Shared mode has no pre-existing controlled local binding."""

    status = "waiting_org_app_binding"

    def __init__(self, profile_name: str) -> None:
        super().__init__(
            f"profile {profile_name!r} has no controlled organisation app binding"
        )
        self.profile_name = profile_name


class AppConfigError(ProfileError):
    """Application configuration could not be completed."""

    status = "app_config_failed"

    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        if status is not None:
            self.status = status


class AppConfigTimeout(AppConfigError):
    status = "app_config_timeout"


class ProfileAlreadyExists(ProfileError):
    status = "profile_exists"


@dataclass(frozen=True)
class AppConfigChallenge:
    profile_name: str
    verification_url: str
    console_url: str | None
    output_path: Path
    context: CliContext | None = field(default=None, repr=False, compare=False)


def ensure_named_profile(
    context: CliContext,
    profile_name: str,
    mode: str = "per_user",
    runner: Callable[..., Any] = subprocess.run,
) -> ProfileState:
    """Discover or create one explicit named profile.

    Per-user mode creates a named profile only when that exact name is absent.
    Shared mode is deliberately non-creating: it accepts only a pre-existing
    local binding and otherwise reports ``waiting_org_app_binding``.
    """
    _validate_profile_name(profile_name)
    selected_mode = _normalise_mode(mode)

    profiles = _list_profiles(context, runner)
    existing = _find_profile(profiles, profile_name)
    if existing is not None:
        app_id = _profile_app_id(existing) or ""
        if selected_mode == "shared":
            if not app_id:
                raise OrgAppBindingRequired(profile_name)
            return ProfileState(profile_name, app_id, "bound")
        return ProfileState(profile_name, app_id, "existing")

    if selected_mode == "shared":
        raise OrgAppBindingRequired(profile_name)

    # A profile being created does not exist yet, so do not bind an unrelated
    # global profile while invoking the CLI's append-only creation command.
    creation_context = _without_profile(context)
    completed, stdout, stderr = _run_sync(
        creation_context,
        ("config", "init", "--new", "--name", profile_name),
        runner,
    )
    if getattr(completed, "returncode", 0) != 0:
        raise AppConfigError(
            "lark-cli config init failed: "
            + redact_sensitive(_diagnostic(stdout, stderr))
        )

    app_id = _extract_app_id(stdout) or _extract_app_id(stderr)
    if not app_id:
        # Some CLI builds print the profile update to stderr and the masked
        # app data to stdout.  Re-read the canonical list when possible, but
        # never turn a successful creation into a second write.
        try:
            profiles = _list_profiles(context, runner)
            refreshed = _find_profile(profiles, profile_name)
            if refreshed is not None:
                app_id = _profile_app_id(refreshed) or ""
        except (IndexError, ProfileError):
            app_id = ""

    return ProfileState(profile_name, app_id, "created")


def begin_app_config(
    context: CliContext,
    profile_name: str,
    runner: Callable[..., Any] = subprocess.Popen,
) -> AppConfigChallenge:
    """Start the official named app-creation flow in the background.

    The command's stdout/stderr are held in an owner-only temporary file.  The
    first usable verification URL is extracted verbatim; query parameters are
    never reconstructed by this module.
    """
    _validate_profile_name(profile_name)
    output_path = _private_output_path()
    command = build_cli_command(
        _without_profile(context),
        "config",
        "init",
        "--new",
        "--name",
        profile_name,
    )
    process: Any = None
    try:
        with output_path.open("r+", encoding="utf-8", errors="replace") as stream:
            process = runner(
                command,
                stdout=stream,
                stderr=stream,
            )
    except FileNotFoundError as error:
        _unlink_quietly(output_path)
        raise AppConfigError(
            f"lark-cli executable unavailable: {context.binary}"
        ) from error
    except OSError as error:
        _unlink_quietly(output_path)
        raise AppConfigError(
            "could not start lark-cli config init: " + redact_sensitive(str(error))
        ) from error

    _append_inline_output(output_path, process)
    output = _wait_for_challenge_output(output_path, process)
    if output is None:
        _terminate_quietly(process)
        raise AppConfigError("lark-cli config init did not emit a verification URL")

    fields = _extract_challenge_fields(output)
    if fields.verification_url is None:
        _terminate_quietly(process)
        raise AppConfigError(
            "lark-cli config init output did not contain a verification URL"
        )

    return AppConfigChallenge(
        profile_name=profile_name,
        verification_url=fields.verification_url,
        console_url=fields.console_url,
        output_path=output_path,
        context=context,
    )


def wait_app_config(
    challenge: AppConfigChallenge,
    timeout_seconds: float = 600,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], Any] = time.sleep,
) -> ProfileState:
    """Poll the CLI's real profile state after the background setup starts."""
    profile_name = challenge.profile_name
    try:
        context = challenge.context or resolve_cli_context(profile=profile_name)
    except CliContextError:
        # A directly constructed challenge has no captured context.  Keep the
        # polling path testable and let the injected/real subprocess runner
        # produce the actual CLI error if this fallback executable is absent.
        context = CliContext(Path("lark-cli"), "", profile_name, frozenset())
    context = replace(context, profile=profile_name)
    deadline = clock() + max(0.0, float(timeout_seconds))
    last_error: ProfileError | None = None

    while True:
        try:
            profiles = _list_profiles(context, subprocess.run)
            profile = _find_profile(profiles, profile_name)
            if profile is not None:
                app_id = _profile_app_id(profile) or ""
                if app_id:
                    return ProfileState(profile_name, app_id, "created")
        except ProfileError as error:
            last_error = error

        now = clock()
        if now >= deadline:
            message = f"timed out waiting for named profile {profile_name!r} to become configured"
            if last_error is not None:
                message += f": {last_error}"
            raise AppConfigTimeout(message)
        sleeper(min(0.5, max(0.0, deadline - now)))


@dataclass(frozen=True)
class _ChallengeFields:
    verification_url: str | None
    console_url: str | None


def _normalise_mode(mode: str) -> str:
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("mode must be a non-empty string")
    normalised = mode.strip().lower().replace("-", "_")
    if normalised in {"per_user", "peruser"}:
        return "per_user"
    if normalised in {"shared", "org", "organization", "org_app"}:
        return "shared"
    raise ValueError(f"unsupported profile mode: {mode!r}")


def _validate_profile_name(profile_name: str) -> None:
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("profile_name must be a non-empty string")
    if any(ord(char) < 32 for char in profile_name):
        raise ValueError("profile_name must not contain control characters")


def _without_profile(context: CliContext) -> CliContext:
    return replace(context, profile=None)


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
        raise AppConfigError(
            f"lark-cli executable unavailable: {context.binary}"
        ) from error
    except OSError as error:
        raise AppConfigError(
            "could not execute lark-cli: " + redact_sensitive(str(error))
        ) from error
    stdout = _text(getattr(completed, "stdout", ""))
    stderr = _text(getattr(completed, "stderr", ""))
    return completed, stdout, stderr


def _list_profiles(context: CliContext, runner: Callable[..., Any]) -> list[dict[str, Any]]:
    completed, stdout, stderr = _run_sync(context, ("profile", "list"), runner)
    if getattr(completed, "returncode", 0) != 0:
        raise AppConfigError(
            "lark-cli profile list failed: "
            + redact_sensitive(_diagnostic(stdout, stderr))
        )

    for payload in _iter_json(stdout + "\n" + stderr):
        entries = _profile_entries(payload)
        if entries is not None:
            return entries
    raise AppConfigError("lark-cli profile list did not return JSON")


def _profile_entries(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        if all(isinstance(item, dict) for item in payload):
            return [item for item in payload if isinstance(item, dict)]
        return None
    if not isinstance(payload, dict):
        return None
    if _profile_name(payload) is not None:
        return [payload]
    for key in ("items", "profiles", "apps"):
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result"):
        value = payload.get(key)
        entries = _profile_entries(value)
        if entries is not None:
            return entries
    return None


def _find_profile(profiles: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for profile in profiles:
        if _profile_name(profile) == name:
            return profile
    return None


def _profile_name(profile: dict[str, Any]) -> str | None:
    for key in ("name", "profile", "profileName", "profile_name"):
        value = profile.get(key)
        if isinstance(value, str):
            return value
    return None


def _profile_app_id(profile: dict[str, Any]) -> str | None:
    for key in ("appId", "app_id", "appID"):
        value = profile.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_app_id(text: str) -> str | None:
    for payload in _iter_json(text):
        if isinstance(payload, dict):
            value = _find_key(payload, ("appId", "app_id", "appID"))
            if isinstance(value, str) and value:
                return value
    match = re.search(r"\bcli_[A-Za-z0-9]+\b", text)
    return match.group(0) if match else None


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


def _private_output_path() -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix="general-screenwriter-lark-config-",
        suffix=".log",
    )
    os.close(descriptor)
    path = Path(raw_path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _wait_for_challenge_output(output_path: Path, process: Any) -> str | None:
    deadline = time.monotonic() + 10.0
    while True:
        output = _read_text(output_path)
        fields = _extract_challenge_fields(output)
        if fields.verification_url is not None:
            return output
        if callable(getattr(process, "poll", None)) and process.poll() is not None:
            return output if output.strip() else None
        if getattr(process, "returncode", None) is not None:
            return output if output.strip() else None
        if time.monotonic() >= deadline:
            return output if output.strip() else None
        time.sleep(0.05)


def _extract_challenge_fields(output: str) -> _ChallengeFields:
    verification: str | None = None
    console: str | None = None

    for payload in _iter_json(output):
        verification = verification or _find_url_value(
            payload,
            ("verification_url", "verification_uri_complete", "verification_uri"),
        )
        console = console or _find_url_value(payload, ("console_url", "consoleUrl"))

    if verification is None:
        verification = _labelled_url(output, ("verification_url", "verification_uri_complete", "verification_uri"))
    if console is None:
        console = _labelled_url(output, ("console_url", "consoleUrl"))

    urls = [_clean_url(match.group(0)) for match in _URL_RE.finditer(output)]
    if verification is None:
        verification = next(
            (url for url in urls if "/page/cli" in url or "user_code=" in url),
            None,
        )
    if verification is None and urls:
        verification = urls[0]
    if console is None:
        console = next(
            (url for url in urls if url != verification and _looks_like_console_url(url)),
            None,
        )
    return _ChallengeFields(verification, console)


def _find_url_value(value: Any, keys: Sequence[str]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for nested in value.values():
            found = _find_url_value(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_url_value(item, keys)
            if found is not None:
                return found
    return None


def _labelled_url(text: str, labels: Sequence[str]) -> str | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?im)(?:{alternatives})\s*[:=]\s*(https?://[^\s<>\"']+)"
    )
    match = pattern.search(text)
    return _clean_url(match.group(1)) if match else None


def _clean_url(url: str) -> str:
    while url and url[-1] in ".,);]":
        url = url[:-1]
    return url


def _looks_like_console_url(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("console", "/app/", "developer"))


def _diagnostic(stdout: str, stderr: str) -> str:
    return " ".join(part.strip() for part in (stdout, stderr) if part.strip())


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _append_inline_output(output_path: Path, process: Any) -> None:
    stdout = getattr(process, "stdout", None)
    stderr = getattr(process, "stderr", None)
    parts = []
    if isinstance(stdout, (str, bytes)):
        parts.append(_text(stdout))
    if isinstance(stderr, (str, bytes)):
        parts.append(_text(stderr))
    if not parts:
        return
    try:
        with output_path.open("a", encoding="utf-8", errors="replace") as stream:
            stream.write("".join(parts))
    except OSError:
        pass


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _terminate_quietly(process: Any) -> None:
    if process is None:
        return
    for method_name in ("terminate", "kill"):
        method = getattr(process, method_name, None)
        if callable(method):
            try:
                method()
            except OSError:
                pass
            return
