"""Additive schema v2 scope-page helpers for the knowledge store."""

import json
import sys
from dataclasses import dataclass, fields as dataclass_fields
from pathlib import Path
from typing import Any, Mapping

SCRIPTS = Path(__file__).resolve().parent
LOADER_SCRIPTS = SCRIPTS.parent.parent / "knowledge-loader" / "scripts"
if str(LOADER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LOADER_SCRIPTS))

from scope_pages import ScopeEnvelope, ScopeEnvelopeError, parse_scope_envelope
from shared_schema import SchemaError


_ENVELOPE_HEADING = "## knowledge-scope"


@dataclass(frozen=True)
class ScopePageCandidate:
    body: str
    metadata: dict[str, Any]
    scope: ScopeEnvelope
    key: str


@dataclass(frozen=True)
class KnowledgeMigrationReport:
    source_kind: str
    source_version: int
    target_version: int
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    ambiguous: tuple[str, ...]
    manual_actions: tuple[str, ...]
    rollback: Mapping[str, Any]


def parse_scope_page(body, metadata) -> ScopeEnvelope | None:
    if not isinstance(body, str):
        raise SchemaError("page body must be text")
    if (not isinstance(metadata, Mapping)
            or not isinstance(metadata.get("key"), str) or not metadata["key"].strip()
            or not isinstance(metadata.get("page_type"), str) or not metadata["page_type"].strip()):
        raise SchemaError("scope pages require metadata with key and page_type")
    try:
        scope = parse_scope_envelope(body)
    except ScopeEnvelopeError as error:
        raise SchemaError(str(error)) from error
    if scope is None:
        return None
    expected = scope_key(scope, metadata["page_type"])
    if metadata["key"] != expected:
        raise SchemaError(
            f"scope metadata does not match the page key: {metadata['key']} != {expected}"
        )
    return scope


def render_scope_page(body: str, scope: ScopeEnvelope) -> str:
    if not isinstance(body, str):
        raise SchemaError("page body must be text")
    if not isinstance(scope, ScopeEnvelope):
        raise SchemaError("scope must be a ScopeEnvelope")
    payload = scope_to_dict(scope)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{body.rstrip(chr(10))}\n\n{_ENVELOPE_HEADING}\n```json\n{rendered}\n```\n"


def scope_to_dict(scope: ScopeEnvelope) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in dataclass_fields(ScopeEnvelope):
        value = getattr(scope, item.name)
        if isinstance(value, tuple):
            result[item.name] = list(value)
        else:
            result[item.name] = value
    return result


def validate_scope_page(candidate) -> ScopePageCandidate:
    body = getattr(candidate, "body", None)
    metadata = getattr(candidate, "metadata", None)
    if not isinstance(body, str) or not isinstance(metadata, Mapping):
        raise SchemaError("candidate must provide body and metadata")
    scope = parse_scope_page(body, metadata)
    if scope is None:
        raise SchemaError("candidate has no scope envelope")
    key = metadata["key"]
    if key in scope.supersedes:
        raise SchemaError(f"scope page cannot supersede itself: {key}")
    if not scope.source_refs:
        raise SchemaError("scope page requires non-empty source_refs")
    return ScopePageCandidate(
        body=body,
        metadata=dict(metadata),
        scope=scope,
        key=key,
    )


def scope_key(scope: ScopeEnvelope, page_type: str) -> str:
    scope_type = getattr(scope, "scope_type", None)
    scope_id = getattr(scope, "scope_id", None)
    if (not isinstance(scope_type, str) or not scope_type.strip()
            or not isinstance(scope_id, str) or not scope_id.strip()
            or not isinstance(page_type, str) or not page_type.strip()):
        raise SchemaError("scope_key requires a parsed scope and non-empty page_type")
    return f"{scope_type}/{scope_id}/{page_type}"


def build_scope_migration_report(inventory) -> KnowledgeMigrationReport:
    matched: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    manual_actions: list[str] = []
    for entry in inventory:
        if (not isinstance(entry, Mapping)
                or not isinstance(entry.get("key"), str) or not entry["key"].strip()):
            missing.append("<unnamed>")
            continue
        key = entry["key"]
        scope = entry.get("scope")
        if scope is None:
            matched.append(key)
            continue
        try:
            expected = scope_key(scope, entry.get("page_type"))
        except SchemaError:
            ambiguous.append(key)
            manual_actions.append(f"{key}: scope metadata is not a parsed envelope")
            continue
        if key == expected:
            matched.append(key)
        else:
            ambiguous.append(key)
            manual_actions.append(f"{key}: key {key} does not match scope key {expected}")
    return KnowledgeMigrationReport(
        source_kind="knowledge_page",
        source_version=1,
        target_version=2,
        matched=tuple(matched),
        missing=tuple(missing),
        ambiguous=tuple(ambiguous),
        manual_actions=tuple(manual_actions),
        rollback={"mode": "read_only", "writes": 0},
    )
