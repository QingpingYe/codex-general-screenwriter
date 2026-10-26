"""Build the v2 knowledge config from user-provided Wiki links.

The bootstrap layer deliberately knows nothing about CLI profiles or credentials.
It resolves only resource identity through the supplied ``LarkCli`` adapter and
stores the resulting schema-v2 configuration using an atomic replace.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Literal, Mapping
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from models import KnowledgeConfig, SourceConfig, TargetConfig


class KnowledgeConfigBootstrapError(ValueError):
    """The supplied Wiki references cannot be resolved without guessing."""

    status = "config_invalid"

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "error": str(self)}


ConfigBootstrapError = KnowledgeConfigBootstrapError


@dataclass(frozen=True)

class WikiReference:
    url: str
    token: str
    space_id: str | None
    root_mode: Literal["space", "node"]


_DEFAULT_LOCK_TTL_MINUTES = 45
_SPACE_QUERY_KEYS = ("space_id", "space")
_NODE_QUERY_KEYS = ("node_token", "token")


def parse_wiki_reference(url: str) -> WikiReference:
    """Parse a Wiki space/node URL or an explicit token without network access."""
    if not isinstance(url, str) or not url.strip():
        raise KnowledgeConfigBootstrapError("a Wiki link or explicit token is required")
    raw = url.strip()

    if "://" not in raw:
        return _parse_explicit_token(raw, url)

    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise KnowledgeConfigBootstrapError("a complete Wiki URL is required")
    if parsed.username is not None or parsed.password is not None:
        raise KnowledgeConfigBootstrapError("Wiki URLs must not contain credentials")

    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if not segments or segments[0].lower() != "wiki":
        raise KnowledgeConfigBootstrapError("link is not a Wiki URL")
    tail = segments[1:]
    path_space_id: str | None = None
    root_mode: Literal["space", "node"]
    token: str

    if len(tail) == 1 and tail[0].lower() not in {"space", "node"}:
        root_mode = "node"
        token = tail[0]
    elif len(tail) == 2 and tail[0].lower() == "space" and tail[1].lower() not in {"node", "space"}:
        root_mode = "space"
        path_space_id = tail[1]
        token = path_space_id
    elif len(tail) >= 3 and tail[0].lower() == "space":
        path_space_id = tail[1]
        if len(tail) == 3 and tail[2].lower() not in {"node", "space"}:
            root_mode = "node"
            token = tail[2]
        elif len(tail) == 4 and tail[2].lower() == "node" and tail[3].lower() not in {"node", "space"}:
            root_mode = "node"
            token = tail[3]
        else:
            raise KnowledgeConfigBootstrapError("Wiki URL has an ambiguous resource path")
    else:
        raise KnowledgeConfigBootstrapError("Wiki URL does not identify a space or node")

    if not token or token.lower() in {"space", "node"}:
        raise KnowledgeConfigBootstrapError("Wiki URL does not identify a resource")

    query = parse_qs(parsed.query, keep_blank_values=False)
    query_space_id = _one_query_identity(query, _SPACE_QUERY_KEYS, "space")
    query_node_token = _one_query_identity(query, _NODE_QUERY_KEYS, "node")

    if path_space_id is not None and query_space_id is not None and path_space_id != query_space_id:
        raise KnowledgeConfigBootstrapError("Wiki URL contains conflicting space identities")
    if root_mode == "space" and query_node_token is not None:
        raise KnowledgeConfigBootstrapError("space URL contains a conflicting node identity")
    if root_mode == "node" and query_node_token is not None and query_node_token != token:
        raise KnowledgeConfigBootstrapError("Wiki URL contains conflicting node identities")
    if root_mode == "node" and path_space_id is None and query_space_id is not None:
        path_space_id = query_space_id

    return WikiReference(url=url, token=token, space_id=path_space_id, root_mode=root_mode)

def build_config_from_links(
    source_url: str,
    target_url: str,
    cli: Any,
) -> KnowledgeConfig:
    """Resolve two Wiki links and return a credential-free schema-v2 config."""
    source = parse_wiki_reference(source_url)
    target = parse_wiki_reference(target_url)
    if _reference_identity(source) == _reference_identity(target):
        raise KnowledgeConfigBootstrapError("source and target must not be the same resource")

    source_identity = _resolve_reference(source, cli)
    target_identity = _resolve_reference(target, cli)
    if source_identity == target_identity:
        raise KnowledgeConfigBootstrapError("source and target resolve to the same resource")

    source_config = SourceConfig(
        space_id=source_identity["space_id"],
        root_mode=source.root_mode,
        wiki_url=_safe_wiki_url(source_url),
    )
    target_config = TargetConfig(
        space_id=target_identity["space_id"],
        root_token=target_identity.get("node_token") if target.root_mode == "node" else None,
        root_mode=target.root_mode,
    )
    binary = getattr(cli, "binary", None)
    candidates = (Path(binary),) if binary is not None else ()
    return KnowledgeConfig(
        source=source_config,
        target=target_config,
        identity="user",
        lock_ttl_minutes=_DEFAULT_LOCK_TTL_MINUTES,
        cli_candidates=candidates,
    )


def write_config_atomic(config: KnowledgeConfig, destination: Path) -> Path:
    """Write ``config`` to ``destination`` with temp-file + ``os.replace`` semantics."""
    if not isinstance(config, KnowledgeConfig):
        raise TypeError("config must be a KnowledgeConfig")
    path = Path(destination).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _config_to_dict(config)

    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
            text=True,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        temporary = None
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parse_explicit_token(raw: str, original: str) -> WikiReference:
    lowered = raw.lower()
    if lowered.startswith("space:"):
        token = raw.split(":", 1)[1].strip()
        if not token or any(character in token for character in "/?#"):
            raise KnowledgeConfigBootstrapError("explicit space token is invalid")
        return WikiReference(original, token, token, "space")
    if lowered.startswith("node:"):
        token = raw.split(":", 1)[1].strip()
        if not token or any(character in token for character in "/?#"):
            raise KnowledgeConfigBootstrapError("explicit node token is invalid")
        return WikiReference(original, token, None, "node")
    if raw.lower().startswith("wiki:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw or any(character in raw for character in "/?#") or re.search(r"\s", raw):
        raise KnowledgeConfigBootstrapError("explicit token is invalid")
    return WikiReference(original, raw, None, "node")


def _one_query_identity(query: Mapping[str, list[str]], keys: tuple[str, ...], label: str) -> str | None:
    values: list[str] = []
    for key in keys:
        for value in query.get(key, ()):
            if value and value not in values:
                values.append(value)
    if len(values) > 1:
        raise KnowledgeConfigBootstrapError(f"Wiki URL contains conflicting {label} identities")
    return values[0] if values else None


def _reference_identity(reference: WikiReference) -> tuple[str, str | None, str]:
    if reference.root_mode == "space":
        return "space", reference.space_id, ""
    return "node", reference.space_id, reference.token
_SENSITIVE_QUERY_KEYS = {
    "appsecret",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "authorization",
    "bearer",
    "devicecode",
    "usercode",
    "token",
}


def _safe_wiki_url(url: str) -> str:
    parsed = urlsplit(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    safe_pairs = [
        (key, value)
        for key, value in pairs
        if re.sub(r"[^a-z0-9]", "", key.lower()) not in _SENSITIVE_QUERY_KEYS
    ]
    if safe_pairs == pairs:
        return url
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_pairs), parsed.fragment))

def _resolve_reference(reference: WikiReference, cli: Any) -> dict[str, Any]:
    if reference.root_mode == "space":
        if not reference.space_id:
            raise KnowledgeConfigBootstrapError("space identity is ambiguous")
        return {"space_id": reference.space_id, "node_token": None, "obj_token": None}

    try:
        payload = cli.get_node(reference.token)
    except Exception as error:  # Convert CLI failures to the stable config status.
        raise KnowledgeConfigBootstrapError(
            f"cannot resolve Wiki node identity: {_safe_error(error)}"
        ) from error
    node = _node_from_payload(payload)
    if not node:
        raise KnowledgeConfigBootstrapError("Wiki node response did not contain a node identity")

    space_id = _first_string(node, "space_id", "spaceId")
    node_token = _first_string(node, "node_token", "nodeToken")
    obj_token = _first_string(node, "obj_token", "objToken", "token")
    if not space_id:
        raise KnowledgeConfigBootstrapError("Wiki node identity is missing space_id")

    expected_token = reference.token
    supplied_identities = {value for value in (node_token, obj_token) if value}
    if supplied_identities and expected_token not in supplied_identities:
        raise KnowledgeConfigBootstrapError("Wiki node identity conflicts with the supplied link")
    if reference.space_id is not None and reference.space_id != space_id:
        raise KnowledgeConfigBootstrapError("Wiki node identity conflicts with the supplied space")

    resolved_token = node_token or expected_token
    return {
        "space_id": space_id,
        "node_token": resolved_token,
        "obj_token": obj_token,
    }


def _node_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    if isinstance(data, Mapping):
        node = data.get("node")
        if isinstance(node, Mapping):
            return dict(node)
        if any(key in data for key in ("space_id", "spaceId", "node_token", "nodeToken")):
            return dict(data)
    node = payload.get("node")
    if isinstance(node, Mapping):
        return dict(node)
    return dict(payload) if any(
        key in payload for key in ("space_id", "spaceId", "node_token", "nodeToken")
    ) else {}


def _first_string(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _safe_error(error: Exception) -> str:
    from lark_cli import redact_sensitive

    return redact_sensitive(str(error)).strip() or type(error).__name__


def _config_to_dict(config: KnowledgeConfig) -> dict[str, Any]:
    target: dict[str, Any] = {
        "space_id": config.target.space_id,
        "root_mode": config.target.root_mode,
    }
    if config.target.root_mode == "node":
        target["root_token"] = config.target.root_token
    return {
        "schema_version": 2,
        "source": {
            "space_id": config.source.space_id,
            "root_mode": config.source.root_mode,
            "wiki_url": config.source.wiki_url,
        },
        "target": target,
        "identity": config.identity,
        "lock_ttl_minutes": config.lock_ttl_minutes,
    }
