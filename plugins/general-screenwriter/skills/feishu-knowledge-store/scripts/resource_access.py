"""Read-only resource ACL diagnostics for the Feishu knowledge store.

Application/user scopes and resource ACLs are deliberately separate outcomes.
A successful ``auth status`` or readable parent never implies a child or target
write permission.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Literal, Mapping

from lark_cli import (
    AuthenticationError,
    LarkCliError,
    PermissionDenied,
    redact_sensitive,
)
from models import KnowledgeConfig


@dataclass(frozen=True)


class ResourceAccessReport:
    status: Literal["ok", "resource_grant_required", "waiting_admin"]
    missing: tuple[str, ...]
    details: tuple[str, ...]

    @property


    def ok(self) -> bool:
        return self.status == "ok"


    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "missing": list(self.missing),
            "details": list(self.details),
        }


class _AccessFailure(RuntimeError):


    def __init__(
        self,
        missing: str | Iterable[str],
        detail: str,
        *,
        status: str = "resource_grant_required",
    ):
        super().__init__(detail)
        if isinstance(missing, str):
            self.missing = (missing,)
        else:
            self.missing = tuple(missing)
        self.detail = detail
        self.status = status


_SCOPE_PATTERN = re.compile(r"\b[a-z][a-z0-9_-]*(?::[a-z0-9_.-]+)+\b", re.IGNORECASE)


def check_resource_access(
    config: KnowledgeConfig,
    cli: Any,
    sample_node_tokens: Iterable[str] = (),
) -> ResourceAccessReport:
    """Check user auth, source reads, target reads, and target edit ACLs."""
    if not isinstance(config, KnowledgeConfig):
        raise TypeError("config must be a KnowledgeConfig")

    identity = getattr(cli, "identity", "user")
    if identity != "user":
        return _report("waiting_admin", ("identity:user",), (
            "the current CLI identity is not a user identity",
        ))

    try:
        auth_payload = _auth_status(cli)
        if isinstance(auth_payload, Mapping) and auth_payload.get("ok") is False:
            raise AuthenticationError("auth status reported failure")
    except AuthenticationError as error:
        return _waiting_for_scope_or_auth(error, "user_authorization")
    except PermissionDenied as error:
        return _waiting_for_scope_or_auth(error, "auth.status")
    except Exception as error:
        return _report("waiting_admin", ("auth.status",), (
            f"user authorization could not be verified: {_safe_error(error)}",
        ))

    try:
        _check_source_read(config, cli, sample_node_tokens)
        target_detail = _check_target_write(config, cli)
    except _AccessFailure as failure:
        return _report(failure.status, failure.missing, (failure.detail,))

    return _report("ok", (), (
        "user identity and source reads were verified",
        target_detail,
    ))


def _check_source_read(config: KnowledgeConfig, cli: Any, sample_node_tokens: Iterable[str]) -> None:
    samples = tuple(token for token in sample_node_tokens if isinstance(token, str) and token.strip())
    source_ref = _parse_source_reference(config)
    if source_ref is None:
        raise _AccessFailure("source.config", "source Wiki link is invalid")

    if source_ref.root_mode == "space":
        try:
            items = cli.list_nodes(config.source.space_id, page_limit=1)
        except Exception as error:
            raise _access_error(error, "source.root", "source space is not readable") from error
        if not samples:
            sampled = _sample_from_items(items)
            if sampled:
                samples = (sampled,)
        if not samples:
            return

    if source_ref.root_mode == "node":
        root = _get_node(cli, source_ref.token, "source.root", "source root is not readable")
        if not samples:
            if not _fetch_node_document(cli, root, "source.sample"):
                raise _AccessFailure("source.sample", "source root document is not readable")
            return
    else:
        root = None

    for sample in samples:
        if source_ref.root_mode == "node" and root is not None:
            root_token = _node_token(root)
            if sample == source_ref.token or sample == root_token:
                node = root
            else:
                node = _get_node(cli, sample, "source.sample", "source sample node is not readable")
        else:
            node = _get_node(cli, sample, "source.sample", "source sample node is not readable")
        node_space = _node_space(node)
        if node_space and node_space != config.source.space_id:
            raise _AccessFailure(
                "source.sample",
                "source sample node belongs to a different space",
            )
        if not _fetch_node_document(cli, node, "source.sample"):
            raise _AccessFailure("source.sample", "source sample document is not readable")


def _check_target_write(config: KnowledgeConfig, cli: Any) -> str:
    if config.target.root_mode == "node":
        root_token = config.target.root_token
        if not isinstance(root_token, str) or not root_token.strip():
            raise _AccessFailure("target.root", "target root token is missing")
        try:
            target_payload = cli.get_node(root_token)
        except Exception as error:
            raise _access_error(error, "target.root", "target root is not readable") from error
        target = _unwrap_node(target_payload)
        if not target:
            raise _AccessFailure("target.root", "target root response did not contain a node")
        target_space = _node_space(target)
        if not target_space or target_space != config.target.space_id:
            raise _AccessFailure(
                "target.root",
                "target root does not belong to the configured target space",
            )
        token = _node_token(target) or root_token
        try:
            allowed = _check_permission(cli, token, "wiki", "edit")
        except PermissionDenied as error:
            if _is_scope_error(error):
                raise _AccessFailure(
                    _scope_missing_key(error),
                    _scope_detail(error, "target edit permission"),
                    status="waiting_admin",
                ) from error
            raise _AccessFailure(
                ("target.edit", "target.acceptance_write"),
                "target edit permission is not available",
            ) from error
        except AuthenticationError as error:
            raise _AccessFailure(
                "user_authorization",
                _scope_detail(error, "target edit permission"),
                status="waiting_admin",
            ) from error
        except Exception as error:
            raise _AccessFailure(
                ("target.edit", "target.acceptance_write"),
                f"target edit permission could not be verified: {_safe_error(error)}",
            ) from error
        if not allowed:
            raise _AccessFailure(
                ("target.edit", "target.acceptance_write"),
                "target edit and acceptance-page write permissions are not available",
            )
        return "target root edit ACL and acceptance-page write permission were verified"

    try:
        items = cli.list_nodes(config.target.space_id, page_limit=1)
    except Exception as error:
        raise _access_error(error, "target.root", "target space is not readable") from error
    if not isinstance(items, (list, tuple)):
        raise _AccessFailure(
            ("target.create", "target.acceptance_write"),
            "target space contents could not be determined safely",
        )
    probe_token = _sample_from_items(items) or config.target.space_id
    _probe_permission_scope(cli, probe_token, "target-space create preflight")
    if not items:
        return (
            "target space is readable and empty; creation ACL preflight is deferred "
            "to the designated initializer"
        )
    raise _AccessFailure(
        ("target.create", "target.acceptance_write"),
        "target space already contains nodes, but root-level create permission "
        "cannot be verified read-only; child edit ACL is not sufficient",
    )


def _probe_permission_scope(cli: Any, token: str, context: str) -> None:
    """Exercise the permission endpoint only to surface missing auth scopes.

    A returned ``auth_result`` is intentionally discarded: it may describe an
    arbitrary node and must never be treated as proof of target-space create
    permission.
    """
    try:
        _check_permission(cli, token, "wiki", "edit")
    except AuthenticationError as error:
        raise _AccessFailure(
            "user_authorization",
            _scope_detail(error, context),
            status="waiting_admin",
        ) from error
    except PermissionDenied as error:
        if _is_scope_error(error):
            raise _AccessFailure(
                _scope_missing_key(error),
                _scope_detail(error, context),
                status="waiting_admin",
            ) from error
        return
    except Exception:
        return


def _auth_status(cli: Any) -> Any:
    caller = getattr(cli, "_json", None)
    if callable(caller):
        return caller("auth", "status", "--json", "--verify")
    preflight = getattr(cli, "preflight", None)
    if callable(preflight):
        return preflight(None, "space")
    return {"identity": getattr(cli, "identity", "user")}


def _check_permission(cli: Any, token: str, resource_type: str, action: str) -> bool:
    checker = getattr(cli, "check_permission", None)
    if callable(checker):
        payload = checker(token, resource_type, action)
        if isinstance(payload, bool):
            return payload
    else:
        caller = getattr(cli, "_json", None)
        if not callable(caller):
            raise LarkCliError("permission checks are not available")
        payload = caller(
            "drive", "permission.members", "auth",
            "--as", str(getattr(cli, "identity", "user")),
            "--token", token,
            "--type", resource_type,
            "--action", action,
            "--format", "json",
        )
    result = _find_bool(payload, ("auth_result", "authResult"))
    if result is None:
        raise LarkCliError("permission response did not contain auth_result")
    return result


def _find_bool(value: Any, keys: tuple[str, ...]) -> bool | None:
    if isinstance(value, Mapping):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, bool):
                return candidate
        for nested in value.values():
            result = _find_bool(nested, keys)
            if result is not None:
                return result
    elif isinstance(value, (list, tuple)):
        for nested in value:
            result = _find_bool(nested, keys)
            if result is not None:
                return result
    return None


def _parse_source_reference(config: KnowledgeConfig):
    try:
        from knowledge_config_bootstrap import parse_wiki_reference
        return parse_wiki_reference(config.source.wiki_url)
    except Exception:
        return None


def _get_node(cli: Any, token: str, missing: str, detail: str) -> Mapping[str, Any]:
    try:
        payload = cli.get_node(token)
    except Exception as error:
        raise _access_error(error, missing, detail) from error
    node = _unwrap_node(payload)
    if not node:
        raise _AccessFailure(missing, detail)
    return node


def _unwrap_node(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    if isinstance(data, Mapping):
        node = data.get("node")
        if isinstance(node, Mapping):
            return node
        if any(key in data for key in ("node_token", "nodeToken", "obj_token", "objToken")):
            return data
    node = payload.get("node")
    if isinstance(node, Mapping):
        return node
    return payload if any(
        key in payload for key in ("node_token", "nodeToken", "obj_token", "objToken")
    ) else {}


def _node_token(node: Mapping[str, Any]) -> str | None:
    return _first_string(node, "node_token", "nodeToken", "token")


def _node_space(node: Mapping[str, Any]) -> str | None:
    return _first_string(node, "space_id", "spaceId")


def _node_document_token(node: Mapping[str, Any]) -> str | None:
    return _first_string(node, "obj_token", "objToken", "document_id", "documentId")


def _first_string(node: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _fetch_node_document(cli: Any, node: Mapping[str, Any], missing: str) -> bool:
    document_token = _node_document_token(node)
    if not document_token:
        raise _AccessFailure(missing, "sample node did not expose a document token")
    try:
        cli.fetch_doc(document_token)
    except AuthenticationError as error:
        raise _AccessFailure(
            "user_authorization",
            _scope_detail(error, "source document read"),
            status="waiting_admin",
        ) from error
    except PermissionDenied as error:
        if _is_scope_error(error):
            raise _AccessFailure(
                _scope_missing_key(error),
                _scope_detail(error, "source document read"),
                status="waiting_admin",
            ) from error
        raise _AccessFailure(missing, "sample document is not readable") from error
    except Exception as error:
        raise _AccessFailure(
            missing,
            f"sample document could not be read: {_safe_error(error)}",
        ) from error
    return True


def _sample_from_items(items: Any) -> str | None:
    if not isinstance(items, (list, tuple)) or not items:
        return None
    first = items[0]
    if isinstance(first, Mapping):
        return _first_string(first, "node_token", "nodeToken", "token", "obj_token", "objToken")
    return first if isinstance(first, str) and first.strip() else None


def _access_error(error: Exception, missing: str, detail: str) -> _AccessFailure:
    if isinstance(error, AuthenticationError):
        return _AccessFailure(
            "user_authorization", _scope_detail(error, detail), status="waiting_admin"
        )
    if isinstance(error, PermissionDenied):
        if _is_scope_error(error):
            return _AccessFailure(
                _scope_missing_key(error),
                _scope_detail(error, detail),
                status="waiting_admin",
            )
        return _AccessFailure(missing, detail)
    if isinstance(error, LarkCliError):
        return _AccessFailure(
            missing,
            f"{detail}: {_safe_error(error)}",
        )
    return _AccessFailure(missing, f"{detail}: {_safe_error(error)}")


def _waiting_for_scope_or_auth(error: Exception, missing: str) -> ResourceAccessReport:
    details = (_scope_detail(error, "user authorization"),) if _is_scope_error(error) else (
        f"user authorization is missing: {_safe_error(error)}",
    )
    return _report("waiting_admin", (missing,), details)


def _is_scope_error(error: Exception) -> bool:
    return "scope" in _safe_error(error).lower()


def _scope_missing_key(error: Exception) -> str:
    match = _SCOPE_PATTERN.search(_safe_error(error))
    return f"scope:{match.group(0)}" if match else "scope"


def _scope_detail(error: Exception, context: str) -> str:
    return (
        f"{context} could not be evaluated because an application/user scope "
        f"is missing: {_safe_error(error)}"
    )


def _safe_error(error: Exception) -> str:
    message = redact_sensitive(str(error)).strip() or type(error).__name__
    return message


def _report(
    status: Literal["ok", "resource_grant_required", "waiting_admin"],
    missing: Iterable[str],
    details: Iterable[str],
) -> ResourceAccessReport:
    unique_missing = tuple(dict.fromkeys(_safe_detail(item) for item in missing if item))
    unique_details = tuple(dict.fromkeys(_safe_detail(item) for item in details if item))
    return ResourceAccessReport(status=status, missing=unique_missing, details=unique_details)


def _safe_detail(value: str) -> str:
    return redact_sensitive(str(value))
