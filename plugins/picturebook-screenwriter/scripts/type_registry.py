"""Read-only registry for screenwriting medium type packs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class TypeRegistryError(ValueError):
    """Raised when a type-pack registry is invalid or a type is unknown."""


@dataclass(frozen=True)
class TypePackDescriptor:
    medium_id: str
    aliases: tuple[str, ...]
    delivery_forms: tuple[str, ...]
    artifact_types: tuple[str, ...]
    workflow_policy: str
    status: str
    legacy_aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypeRegistry:
    packs: tuple[TypePackDescriptor, ...]


_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "type-packs.json"
_PACK_REQUIRED = {
    "medium_id", "aliases", "delivery_forms", "artifact_types",
    "workflow_policy", "status",
}
_PACK_OPTIONAL = {"legacy_aliases"}


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _string_list(value: Any, label: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeRegistryError(f"{label} must be an array")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise TypeRegistryError(f"{label} entries must be non-empty strings")
        item = item.strip()
        key = _normalized_name(item)
        if key in seen:
            raise TypeRegistryError(f"{label} contains duplicate value: {item}")
        seen.add(key)
        normalized.append(item)
    if not allow_empty and not normalized:
        raise TypeRegistryError(f"{label} must not be empty")
    return tuple(normalized)


def load_type_registry(path: str | Path | None = None) -> TypeRegistry:
    """Load and validate the JSON type-pack registry."""
    source = Path(path) if path is not None else _REGISTRY_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TypeRegistryError(f"cannot read type registry: {source}") from error
    return parse_type_registry(payload)


def parse_type_registry(payload: Any) -> TypeRegistry:
    """Validate an in-memory registry payload and build its descriptors."""
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "packs"}:
        raise TypeRegistryError("registry must contain schema_version and packs")
    if payload["schema_version"] != 1:
        raise TypeRegistryError("unsupported type registry schema_version")
    if not isinstance(payload["packs"], list) or not payload["packs"]:
        raise TypeRegistryError("packs must be a non-empty array")

    packs: list[TypePackDescriptor] = []
    names: dict[str, str] = {}
    for index, item in enumerate(payload["packs"]):
        label = f"packs[{index}]"
        if not isinstance(item, dict):
            raise TypeRegistryError(f"{label} must be an object")
        keys = set(item)
        if not _PACK_REQUIRED <= keys or keys - _PACK_REQUIRED - _PACK_OPTIONAL:
            raise TypeRegistryError(f"{label} has missing or unknown fields")

        medium_id = item["medium_id"]
        if not isinstance(medium_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*", medium_id.strip().casefold()
        ):
            raise TypeRegistryError(f"{label}.medium_id is invalid")
        medium_id = medium_id.strip().casefold()
        aliases = _string_list(item["aliases"], f"{label}.aliases", allow_empty=True)
        delivery_forms = _string_list(
            item["delivery_forms"], f"{label}.delivery_forms", allow_empty=False
        )
        artifact_types = _string_list(
            item["artifact_types"], f"{label}.artifact_types", allow_empty=True
        )
        legacy_aliases = _string_list(
            item.get("legacy_aliases", []),
            f"{label}.legacy_aliases",
            allow_empty=True,
        )
        workflow_policy = item["workflow_policy"]
        if not isinstance(workflow_policy, str) or not workflow_policy.strip():
            raise TypeRegistryError(f"{label}.workflow_policy must be non-empty")
        status = item["status"]
        if status not in {"active", "planned"}:
            raise TypeRegistryError(f"{label}.status must be active or planned")

        descriptor = TypePackDescriptor(
            medium_id=medium_id,
            aliases=aliases,
            delivery_forms=delivery_forms,
            artifact_types=artifact_types,
            workflow_policy=workflow_policy.strip(),
            status=status,
            legacy_aliases=legacy_aliases,
        )
        for name in (medium_id, *aliases, *legacy_aliases):
            key = _normalized_name(name)
            previous = names.get(key)
            if previous is not None:
                raise TypeRegistryError(
                    f"type identifier collision: {name!r} is already used by {previous}"
                )
            names[key] = medium_id
        packs.append(descriptor)
    return TypeRegistry(tuple(packs))


def resolve_type_pack(registry: TypeRegistry, identifier: str) -> TypePackDescriptor:
    """Resolve a canonical ID, display alias, or legacy alias."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise TypeRegistryError("type identifier must be a non-empty string")
    key = _normalized_name(identifier)
    for pack in registry.packs:
        candidates = (pack.medium_id, *pack.aliases, *pack.legacy_aliases)
        if any(_normalized_name(candidate) == key for candidate in candidates):
            return pack
    raise TypeRegistryError(f"unknown medium_id: {identifier!r}")


@lru_cache(maxsize=1)
def default_type_registry() -> TypeRegistry:
    return load_type_registry()


def canonical_medium_id(identifier: str) -> str:
    """Return the canonical ID for a registry ID or alias."""
    return resolve_type_pack(default_type_registry(), identifier).medium_id
