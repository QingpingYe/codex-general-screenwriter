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


class TypePackNotExecutableError(TypeRegistryError):
    """Raised when a planned type pack is used as an executable workflow."""


class ArtifactContractError(TypeRegistryError):
    """Raised when an artifact contract is invalid or unknown."""


class StageContractError(TypeRegistryError):
    """Raised when a stage contract is invalid or unknown."""


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_id: str
    aliases: tuple[str, ...] = ()
    delivery_forms: tuple[str, ...] = ()
    stage_id: str = ""
    depends_on: tuple[str, ...] = ()
    required: bool = True
    validator: str | None = None
    exporter: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class StageContract:
    stage_id: str
    aliases: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    confirmation_required: bool = False
    status: str = "active"


@dataclass(frozen=True)
class TypePackDescriptor:
    medium_id: str
    aliases: tuple[str, ...]
    delivery_forms: tuple[str, ...]
    artifact_types: tuple[ArtifactDescriptor, ...]
    workflow_policy: str
    status: str
    legacy_aliases: tuple[str, ...] = ()
    version: str = "legacy-v1"
    stages: tuple[StageContract, ...] = ()
    validators: tuple[str, ...] = ()
    exporters: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        """Return canonical artifact IDs for legacy callers."""
        return tuple(artifact.artifact_id for artifact in self.artifact_types)


@dataclass(frozen=True)
class TypeRegistry:
    packs: tuple[TypePackDescriptor, ...]


_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "type-packs.json"
_PACK_REQUIRED = {
    "medium_id", "aliases", "delivery_forms", "artifact_types",
    "workflow_policy", "status",
}
_PACK_OPTIONAL = {
    "legacy_aliases", "version", "stages", "validators", "exporters",
    "capabilities",
}
_ARTIFACT_FIELDS = {
    "artifact_id", "aliases", "delivery_forms", "stage_id", "depends_on",
    "required", "validator", "exporter", "status",
}
_STAGE_FIELDS = {
    "stage_id", "aliases", "depends_on", "artifact_ids",
    "confirmation_required", "status",
}


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


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeRegistryError(f"{label} must be null or a non-empty string")
    return value.strip()


def _parse_artifact_descriptor(
    value: Any,
    label: str,
    *,
    default_delivery_forms: tuple[str, ...],
) -> ArtifactDescriptor:
    if not isinstance(value, dict):
        raise ArtifactContractError(f"{label} must be an object")
    if set(value) != _ARTIFACT_FIELDS:
        raise ArtifactContractError(f"{label} has missing or unknown fields")
    artifact_id = value["artifact_id"]
    if not isinstance(artifact_id, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]*", artifact_id.strip().casefold()
    ):
        raise ArtifactContractError(f"{label}.artifact_id is invalid")
    artifact_id = artifact_id.strip().casefold()
    aliases = _string_list(value["aliases"], f"{label}.aliases", allow_empty=True)
    delivery_forms = _string_list(
        value["delivery_forms"], f"{label}.delivery_forms", allow_empty=False
    )
    stage_id = value["stage_id"]
    if not isinstance(stage_id, str) or not stage_id.strip():
        raise ArtifactContractError(f"{label}.stage_id must be non-empty")
    depends_on = _string_list(
        value["depends_on"], f"{label}.depends_on", allow_empty=True
    )
    required = value["required"]
    if not isinstance(required, bool):
        raise ArtifactContractError(f"{label}.required must be boolean")
    validator = _optional_string(value["validator"], f"{label}.validator")
    exporter = _optional_string(value["exporter"], f"{label}.exporter")
    status = value["status"]
    if status not in {"active", "planned"}:
        raise ArtifactContractError(f"{label}.status must be active or planned")
    if not set(delivery_forms).issubset(default_delivery_forms):
        unknown = sorted(set(delivery_forms) - set(default_delivery_forms))
        raise ArtifactContractError(
            f"{label}.delivery_forms contains unsupported values: {unknown}"
        )
    return ArtifactDescriptor(
        artifact_id=artifact_id,
        aliases=aliases,
        delivery_forms=delivery_forms,
        stage_id=stage_id.strip(),
        depends_on=depends_on,
        required=required,
        validator=validator,
        exporter=exporter,
        status=status,
    )


def _parse_artifact_types(
    value: Any,
    label: str,
    *,
    default_delivery_forms: tuple[str, ...],
) -> tuple[ArtifactDescriptor, ...]:
    if not isinstance(value, list):
        raise TypeRegistryError(f"{label} must be an array")
    if not value:
        return ()
    if all(isinstance(item, str) for item in value):
        ids = _string_list(value, label, allow_empty=True)
        return tuple(
            ArtifactDescriptor(artifact_id=artifact_id)
            for artifact_id in ids
        )
    if any(isinstance(item, str) for item in value):
        raise ArtifactContractError(f"{label} cannot mix strings and objects")
    return tuple(
        _parse_artifact_descriptor(
            item,
            f"{label}[{index}]",
            default_delivery_forms=default_delivery_forms,
        )
        for index, item in enumerate(value)
    )


def _parse_stage_contract(value: Any, label: str) -> StageContract:
    if not isinstance(value, dict):
        raise StageContractError(f"{label} must be an object")
    if set(value) != _STAGE_FIELDS:
        raise StageContractError(f"{label} has missing or unknown fields")
    stage_id = value["stage_id"]
    if not isinstance(stage_id, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]*", stage_id.strip().casefold()
    ):
        raise StageContractError(f"{label}.stage_id is invalid")
    status = value["status"]
    if status not in {"active", "planned"}:
        raise StageContractError(f"{label}.status must be active or planned")
    confirmation_required = value["confirmation_required"]
    if not isinstance(confirmation_required, bool):
        raise StageContractError(f"{label}.confirmation_required must be boolean")
    return StageContract(
        stage_id=stage_id.strip(),
        aliases=_string_list(value["aliases"], f"{label}.aliases", allow_empty=True),
        depends_on=_string_list(
            value["depends_on"], f"{label}.depends_on", allow_empty=True
        ),
        artifact_ids=_string_list(
            value["artifact_ids"], f"{label}.artifact_ids", allow_empty=True
        ),
        confirmation_required=confirmation_required,
        status=status,
    )


def _validate_local_names(
    values: tuple[str, ...], label: str, *, error_type: type[TypeRegistryError]
) -> None:
    seen: set[str] = set()
    for value in values:
        key = _normalized_name(value)
        if key in seen:
            raise error_type(f"{label} contains duplicate identifier: {value}")
        seen.add(key)


def validate_type_contract(type_pack: TypePackDescriptor) -> TypePackDescriptor:
    """Validate one normalized type-pack contract and return it unchanged."""
    if type_pack.status not in {"active", "planned"}:
        raise TypeRegistryError(
            f"type pack {type_pack.medium_id!r}.status must be active or planned"
        )
    if not type_pack.version.strip():
        raise TypeRegistryError(f"type pack {type_pack.medium_id!r}.version must be non-empty")
    if not type_pack.workflow_policy.strip():
        raise TypeRegistryError(
            f"type pack {type_pack.medium_id!r}.workflow_policy must be non-empty"
        )

    artifact_ids = tuple(artifact.artifact_id for artifact in type_pack.artifact_types)
    _validate_local_names(
        artifact_ids,
        f"type pack {type_pack.medium_id}.artifacts",
        error_type=ArtifactContractError,
    )
    artifact_names = set(_normalized_name(value) for value in artifact_ids)
    for artifact in type_pack.artifact_types:
        names = (artifact.artifact_id, *artifact.aliases)
        _validate_local_names(
            names,
            f"artifact {artifact.artifact_id}",
            error_type=ArtifactContractError,
        )
        for name in artifact.aliases:
            key = _normalized_name(name)
            if key in artifact_names:
                raise ArtifactContractError(
                    f"artifact alias collision: {name!r} in {type_pack.medium_id}"
                )
            artifact_names.add(key)

    stage_ids = tuple(stage.stage_id for stage in type_pack.stages)
    _validate_local_names(
        stage_ids,
        f"type pack {type_pack.medium_id}.stages",
        error_type=StageContractError,
    )
    stage_names = set(_normalized_name(value) for value in stage_ids)
    for stage in type_pack.stages:
        names = (stage.stage_id, *stage.aliases)
        _validate_local_names(
            names,
            f"stage {stage.stage_id}",
            error_type=StageContractError,
        )
        for name in stage.aliases:
            key = _normalized_name(name)
            if key in stage_names:
                raise StageContractError(
                    f"stage alias collision: {name!r} in {type_pack.medium_id}"
                )
            stage_names.add(key)

    structured = bool(type_pack.stages) or any(
        artifact.stage_id for artifact in type_pack.artifact_types
    )
    if structured and type_pack.version == "legacy-v1":
        raise TypeRegistryError(
            f"type pack {type_pack.medium_id!r}.version is required for structured contracts"
        )
    if structured and type_pack.status == "active" and not type_pack.stages:
        raise StageContractError(
            f"type pack {type_pack.medium_id!r}.stages must not be empty for active contracts"
        )

    artifact_id_set = set(artifact_ids)
    stage_id_set = set(stage_ids)
    for artifact in type_pack.artifact_types:
        if artifact.stage_id and artifact.stage_id not in stage_id_set:
            raise StageContractError(
                f"artifact {artifact.artifact_id!r} references unknown stage "
                f"{artifact.stage_id!r}"
            )
        unknown_dependencies = sorted(
            set(artifact.depends_on) - artifact_id_set
        )
        if unknown_dependencies:
            raise ArtifactContractError(
                f"artifact {artifact.artifact_id!r} references unknown dependencies: "
                f"{unknown_dependencies}"
            )
        if not set(artifact.delivery_forms).issubset(type_pack.delivery_forms):
            unknown_forms = sorted(
                set(artifact.delivery_forms) - set(type_pack.delivery_forms)
            )
            raise ArtifactContractError(
                f"artifact {artifact.artifact_id!r} has unsupported delivery forms: "
                f"{unknown_forms}"
            )

    for stage in type_pack.stages:
        unknown_dependencies = sorted(set(stage.depends_on) - stage_id_set)
        if unknown_dependencies:
            raise StageContractError(
                f"stage {stage.stage_id!r} references unknown dependencies: "
                f"{unknown_dependencies}"
            )
        unknown_artifacts = sorted(set(stage.artifact_ids) - artifact_id_set)
        if unknown_artifacts:
            raise StageContractError(
                f"stage {stage.stage_id!r} references unknown artifacts: "
                f"{unknown_artifacts}"
            )
    return type_pack


def _validate_global_artifact_aliases(packs: tuple[TypePackDescriptor, ...]) -> None:
    type_names: dict[str, str] = {}
    for pack in packs:
        for name in (pack.medium_id, *pack.aliases, *pack.legacy_aliases):
            type_names[_normalized_name(name)] = pack.medium_id
    for pack in packs:
        for artifact in pack.artifact_types:
            for name in artifact.aliases:
                key = _normalized_name(name)
                owner = type_names.get(key)
                if owner is not None:
                    raise ArtifactContractError(
                        f"artifact alias collision: {name!r} is used by type pack {owner!r}"
                    )


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
        raw_artifacts = item["artifact_types"]
        artifact_types = _parse_artifact_types(
            raw_artifacts,
            f"{label}.artifact_types",
            default_delivery_forms=delivery_forms,
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
        stages_value = item.get("stages", [])
        if not isinstance(stages_value, list):
            raise StageContractError(f"{label}.stages must be an array")
        stages = tuple(
            _parse_stage_contract(stage, f"{label}.stages[{stage_index}]")
            for stage_index, stage in enumerate(stages_value)
        )
        structured = bool(stages) or any(
            isinstance(artifact, dict) for artifact in raw_artifacts
        )
        if structured and "version" not in item:
            raise TypeRegistryError(f"{label}.version is required for structured contracts")
        version = item.get("version", "legacy-v1")
        if not isinstance(version, str) or not version.strip():
            raise TypeRegistryError(f"{label}.version must be non-empty")
        validators = _string_list(
            item.get("validators", []), f"{label}.validators", allow_empty=True
        )
        exporters = _string_list(
            item.get("exporters", []), f"{label}.exporters", allow_empty=True
        )
        capabilities = _string_list(
            item.get("capabilities", []), f"{label}.capabilities", allow_empty=True
        )

        descriptor = TypePackDescriptor(
            medium_id=medium_id,
            version=version.strip(),
            aliases=aliases,
            delivery_forms=delivery_forms,
            artifact_types=artifact_types,
            workflow_policy=workflow_policy.strip(),
            status=status,
            legacy_aliases=legacy_aliases,
            stages=stages,
            validators=validators,
            exporters=exporters,
            capabilities=capabilities,
        )
        validate_type_contract(descriptor)
        for name in (medium_id, *aliases, *legacy_aliases):
            key = _normalized_name(name)
            previous = names.get(key)
            if previous is not None:
                raise TypeRegistryError(
                    f"type identifier collision: {name!r} is already used by {previous}"
                )
            names[key] = medium_id
        packs.append(descriptor)
    registry = TypeRegistry(tuple(packs))
    _validate_global_artifact_aliases(registry.packs)
    return registry


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


def resolve_artifact(
    type_pack: TypePackDescriptor, identifier: str
) -> ArtifactDescriptor:
    """Resolve an artifact ID or alias within one type pack."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise ArtifactContractError("artifact identifier must be a non-empty string")
    key = _normalized_name(identifier)
    for artifact in type_pack.artifact_types:
        if any(
            _normalized_name(candidate) == key
            for candidate in (artifact.artifact_id, *artifact.aliases)
        ):
            return artifact
    raise ArtifactContractError(
        f"unknown artifact {identifier!r} in type pack {type_pack.medium_id!r}"
    )


def resolve_stage(type_pack: TypePackDescriptor, identifier: str) -> StageContract:
    """Resolve a stage ID or alias within one type pack."""
    if not isinstance(identifier, str) or not identifier.strip():
        raise StageContractError("stage identifier must be a non-empty string")
    key = _normalized_name(identifier)
    for stage in type_pack.stages:
        if any(
            _normalized_name(candidate) == key
            for candidate in (stage.stage_id, *stage.aliases)
        ):
            return stage
    raise StageContractError(
        f"unknown stage {identifier!r} in type pack {type_pack.medium_id!r}"
    )


def assert_type_pack_executable(type_pack: TypePackDescriptor) -> None:
    """Reject planned packs at the workflow execution boundary."""
    if type_pack.status != "active":
        raise TypePackNotExecutableError(
            f"type pack {type_pack.medium_id!r} is not executable (status={type_pack.status!r})"
        )


@lru_cache(maxsize=1)
def default_type_registry() -> TypeRegistry:
    return load_type_registry()


def canonical_medium_id(identifier: str) -> str:
    """Return the canonical ID for a registry ID or alias."""
    return resolve_type_pack(default_type_registry(), identifier).medium_id
