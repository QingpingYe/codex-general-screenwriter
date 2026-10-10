import json
import re
from dataclasses import dataclass, field


SCOPE_TYPES = {
    "task",
    "scene",
    "episode",
    "season",
    "project",
    "series",
    "genre",
    "medium",
    "global",
}

AUTHORITIES = {
    "system",
    "type_pack",
    "series",
    "project",
    "user_experiment",
}

_ENVELOPE_RE = re.compile(
    r"(?ms)^## knowledge-scope\n```json\n(.*?)\n```\s*$"
)


class ScopeEnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class ScopeEnvelope:
    schema_version: int
    scope_type: str
    scope_id: str
    authority: str
    medium_id: str | None = None
    genre_ids: tuple[str, ...] = ()
    version: int = 1
    depends_on: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    built_against: dict = field(default_factory=dict)


def parse_scope_envelope(body: str):
    if not isinstance(body, str):
        raise ScopeEnvelopeError("page body must be text")
    matches = _ENVELOPE_RE.findall(body)
    if not matches:
        return None
    if len(matches) != 1:
        raise ScopeEnvelopeError("page body must contain at most one scope envelope")
    try:
        payload = json.loads(matches[0])
    except json.JSONDecodeError as error:
        raise ScopeEnvelopeError("scope envelope is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ScopeEnvelopeError("scope envelope must be an object")
    required = {"schema_version", "scope_type", "scope_id", "authority"}
    optional = {
        "medium_id",
        "genre_ids",
        "version",
        "depends_on",
        "source_refs",
        "built_against",
    "supersedes",
    }
    if not required <= set(payload) or not set(payload) <= required | optional:
        raise ScopeEnvelopeError("scope envelope has missing or unknown fields")
    if payload["schema_version"] != 2:
        raise ScopeEnvelopeError("unsupported scope envelope schema_version")
    if payload["scope_type"] not in SCOPE_TYPES:
        raise ScopeEnvelopeError(f"unknown scope_type: {payload['scope_type']}")
    if payload["authority"] not in AUTHORITIES:
        raise ScopeEnvelopeError(f"unknown authority: {payload['authority']}")
    if not isinstance(payload["scope_id"], str) or not payload["scope_id"].strip():
        raise ScopeEnvelopeError("scope_id must be non-empty")
    medium_id = payload.get("medium_id")
    if medium_id is not None and (not isinstance(medium_id, str) or not medium_id.strip()):
        raise ScopeEnvelopeError("medium_id must be non-empty when present")
    genre_ids = payload.get("genre_ids", ())
    if not isinstance(genre_ids, list) or any(not isinstance(item, str) or not item.strip() for item in genre_ids):
        raise ScopeEnvelopeError("genre_ids must be a list of non-empty strings")
    version = payload.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ScopeEnvelopeError("version must be a positive integer")
    depends_on = payload.get("depends_on", ())
    source_refs = payload.get("source_refs", ())
    if not isinstance(depends_on, list) or any(not isinstance(item, str) or not item.strip() for item in depends_on):
        raise ScopeEnvelopeError("depends_on must be a list of non-empty strings")
    if not isinstance(source_refs, list) or any(not isinstance(item, str) or not item.strip() for item in source_refs):
        raise ScopeEnvelopeError("source_refs must be a list of non-empty strings")
    supersedes = payload.get("supersedes", [])
    if not isinstance(supersedes, list) or any(not isinstance(item, str) or not item.strip() for item in supersedes):
        raise ScopeEnvelopeError("supersedes must be a list of non-empty strings")
    built_against = payload.get("built_against", {})
    if not isinstance(built_against, dict):
        raise ScopeEnvelopeError("built_against must be an object")
    return ScopeEnvelope(
        schema_version=2,
        scope_type=payload["scope_type"],
        scope_id=payload["scope_id"].strip(),
        authority=payload["authority"],
        medium_id=medium_id,
        genre_ids=tuple(genre_ids),
        version=version,
        depends_on=tuple(depends_on),
        source_refs=tuple(source_refs),
        supersedes=tuple(supersedes),
        built_against=built_against,
    )
