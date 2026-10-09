"""Immutable type-pack contracts; configuration loading never executes code."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class TypeRegistryError(ValueError):
    """Invalid registry or unknown medium."""


class TypePackNotExecutableError(TypeRegistryError):
    """A planned or read-only legacy pack cannot execute."""


class ArtifactContractError(TypeRegistryError):
    """Invalid or unknown artifact contract."""


class StageContractError(TypeRegistryError):
    """Invalid or unknown stage contract."""


class WorkflowContractError(TypeRegistryError):
    """Invalid or unknown optional workflow."""


def _freeze_sequences(instance, names):
    for name in names:
        value = getattr(instance, name)
        if not isinstance(value, (tuple, list)):
            raise TypeError(f"{name} must be a list or tuple")
        object.__setattr__(instance, name, tuple(value))


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_id: str
    aliases: tuple[str, ...] = ()
    delivery_forms: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    origin: str = "workflow_output"
    input_stage: str | None = None
    production_stage: str | None = None
    validation_stages: tuple[str, ...] = ()
    validator: str | None = None
    exporter: str | None = None
    status: str = "active"

    def __post_init__(self):
        _freeze_sequences(self, ("aliases", "delivery_forms", "depends_on", "validation_stages"))


@dataclass(frozen=True)
class StageContract:
    stage_id: str
    aliases: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    consumes_artifact_ids: tuple[str, ...] = ()
    produces_artifact_ids: tuple[str, ...] = ()
    validates_artifact_ids: tuple[str, ...] = ()
    confirmation_required: bool = False
    status: str = "active"
    stage_type: str | None = None
    owner: str | None = None
    gate: str = "none"

    def __post_init__(self):
        _freeze_sequences(self, (
            "aliases", "depends_on", "consumes_artifact_ids",
            "produces_artifact_ids", "validates_artifact_ids",
        ))


@dataclass(frozen=True)
class WorkflowInputRequirement:
    artifact_id: str
    required_status: str


@dataclass(frozen=True)
class WorkflowContract:
    workflow_id: str
    trigger_intent: str
    inputs: tuple[WorkflowInputRequirement, ...] = ()
    artifact_types: tuple[ArtifactDescriptor, ...] = ()
    stages: tuple[StageContract, ...] = ()
    required: bool = False
    blocks_core_completion: bool = False

    def __post_init__(self):
        _freeze_sequences(self, ("inputs", "artifact_types", "stages"))


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
    optional_workflows: tuple[WorkflowContract, ...] = ()
    contract_schema: str = "type-pack-contract-v1"

    def __post_init__(self):
        _freeze_sequences(self, (
            "aliases", "delivery_forms", "artifact_types", "legacy_aliases",
            "stages", "validators", "exporters", "capabilities", "optional_workflows",
        ))

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        """Canonical core IDs for callers that previously consumed strings."""
        return tuple(a.artifact_id for a in self.artifact_types)


@dataclass(frozen=True)
class TypeRegistry:
    packs: tuple[TypePackDescriptor, ...]

    def __post_init__(self):
        _freeze_sequences(self, ("packs",))


_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "type-packs.json"
_PACK_REQUIRED = {"medium_id", "aliases", "delivery_forms", "artifact_types", "workflow_policy", "status"}
_PACK_OPTIONAL = {"legacy_aliases", "version", "stages", "validators", "exporters", "capabilities", "optional_workflows"}
_ARTIFACT_FIELDS = set(ArtifactDescriptor.__dataclass_fields__)
_STAGE_FIELDS = set(StageContract.__dataclass_fields__)
_STAGE_OPTIONAL = {"stage_type", "owner"}
_WORKFLOW_FIELDS = set(WorkflowContract.__dataclass_fields__)
STAGE_TYPES = {
    "session_init", "brief_gate", "knowledge_load", "delegation", "creation",
    "validation", "synthesis", "confirmation", "persistence", "export",
    "delivery",
}


def _normalized_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _text(value, label, error=TypeRegistryError):
    if not isinstance(value, str) or not value.strip():
        raise error(f"{label} 必须是非空字符串")
    return value.strip()


def _id(value, label, error=TypeRegistryError):
    value = _text(value, label, error).casefold()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise error(f"{label} 标识无效：{value!r}")
    return value


def _status(value, label, error):
    if not isinstance(value, str) or value not in ("active", "planned"):
        raise error(f"{label} 必须是 active 或 planned")
    return value


def _boolean(value, label, error):
    if type(value) is not bool:
        raise error(f"{label} 必须是布尔值")
    return value


def _strings(value, label, error=TypeRegistryError, *, empty=True):
    if not isinstance(value, (list, tuple)):
        raise error(f"{label} 必须是数组")
    result = tuple(_text(item, label, error) for item in value)
    keys = [_normalized_name(item) for item in result]
    if len(keys) != len(set(keys)):
        raise error(f"{label} 有重复标识")
    if not empty and not result:
        raise error(f"{label} 不得为空")
    return result


def _nullable_text(value, label, error):
    return None if value is None else _text(value, label, error)


def _object(value, required, optional, label, error):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise error(f"{label} 必须是字符串键对象")
    if not required <= set(value) or set(value) - required - optional:
        raise error(f"{label} 包含缺失或未知字段")
    return value


def _objects(value, label, parser, error):
    if not isinstance(value, (list, tuple)):
        raise error(f"{label} 必须是数组")
    return tuple(parser(item, f"{label}[{index}]") for index, item in enumerate(value))


def _parse_artifact(raw, label):
    _object(raw, _ARTIFACT_FIELDS, set(), label, ArtifactContractError)
    error = ArtifactContractError
    origin = raw["origin"]
    if not isinstance(origin, str) or origin not in ("user_input", "workflow_output"):
        raise error(f"{label}.origin 必须是 user_input 或 workflow_output")
    return ArtifactDescriptor(
        artifact_id=_id(raw["artifact_id"], f"{label}.artifact_id", error),
        aliases=_strings(raw["aliases"], f"{label}.aliases", error),
        delivery_forms=_strings(raw["delivery_forms"], f"{label}.delivery_forms", error, empty=False),
        depends_on=_strings(raw["depends_on"], f"{label}.depends_on", error), origin=origin,
        input_stage=_nullable_text(raw["input_stage"], f"{label}.input_stage", error),
        production_stage=_nullable_text(raw["production_stage"], f"{label}.production_stage", error),
        validation_stages=_strings(raw["validation_stages"], f"{label}.validation_stages", error),
        validator=_nullable_text(raw["validator"], f"{label}.validator", error),
        exporter=_nullable_text(raw["exporter"], f"{label}.exporter", error),
        status=_status(raw["status"], f"{label}.status", error),
    )


def _parse_stage(raw, label):
    _object(raw, _STAGE_FIELDS - _STAGE_OPTIONAL, _STAGE_OPTIONAL, label, StageContractError)
    error = StageContractError
    return StageContract(
        stage_id=_id(raw["stage_id"], f"{label}.stage_id", error),
        **{name: _strings(raw[name], f"{label}.{name}", error) for name in (
            "aliases", "depends_on", "consumes_artifact_ids", "produces_artifact_ids", "validates_artifact_ids",
        )},
        confirmation_required=_boolean(raw["confirmation_required"], f"{label}.confirmation_required", error),
        status=_status(raw["status"], f"{label}.status", error),
        stage_type=_nullable_text(raw.get("stage_type"), f"{label}.stage_type", error),
        owner=_nullable_text(raw.get("owner"), f"{label}.owner", error),
        gate=_text(raw["gate"], f"{label}.gate", error),
    )


def _parse_workflow(raw, label):
    _object(raw, _WORKFLOW_FIELDS, set(), label, WorkflowContractError)
    def parse_input(item, input_label):
        _object(item, {"artifact_id", "required_status"}, set(), input_label, WorkflowContractError)
        return WorkflowInputRequirement(
            _id(item["artifact_id"], f"{input_label}.artifact_id", WorkflowContractError),
            _text(item["required_status"], f"{input_label}.required_status", WorkflowContractError),
        )
    return WorkflowContract(
        workflow_id=_id(raw["workflow_id"], f"{label}.workflow_id", WorkflowContractError),
        trigger_intent=_text(raw["trigger_intent"], f"{label}.trigger_intent", WorkflowContractError),
        inputs=_objects(raw["inputs"], f"{label}.inputs", parse_input, WorkflowContractError),
        artifact_types=_objects(raw["artifact_types"], f"{label}.artifacts", _parse_artifact, ArtifactContractError),
        stages=_objects(raw["stages"], f"{label}.stages", _parse_stage, StageContractError),
        required=_boolean(raw["required"], f"{label}.required", WorkflowContractError),
        blocks_core_completion=_boolean(raw["blocks_core_completion"], f"{label}.blocks_core_completion", WorkflowContractError),
    )


def _index(descriptors, id_field, label, error):
    ids, names = {}, set()
    for item in descriptors:
        identifier = _id(getattr(item, id_field), label, error)
        for name in (identifier, *_strings(item.aliases, label, error)):
            key = _normalized_name(name)
            if key in names:
                raise error(f"{label} 标识/别名冲突：{name!r}")
            names.add(key)
        ids[identifier] = item
    return ids


def _acyclic(graph, label, error):
    # Remove leaves iteratively to avoid recursion limits on large type packs.
    incoming = {node: len(deps) for node, deps in graph.items()}
    dependents = {node: [] for node in graph}
    for node, deps in graph.items():
        for dependency in deps:
            dependents[dependency].append(node)
    ready = [node for node, count in incoming.items() if count == 0]
    count = 0
    while ready:
        node = ready.pop()
        count += 1
        for dependent in dependents[node]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                ready.append(dependent)
    if count != len(graph):
        raise error(f"{label} 依赖存在环")


def _upstream(stages, stage_id):
    seen, pending = set(), list(stages[stage_id].depends_on)
    while pending:
        sid = pending.pop()
        if sid not in seen:
            seen.add(sid)
            pending.extend(stages[sid].depends_on)
    return seen


def _validate_scope(pack, artifacts, stages, external=()):
    amap = _index(artifacts, "artifact_id", f"artifact/{pack.medium_id}", ArtifactContractError)
    smap = _index(stages, "stage_id", f"stage/{pack.medium_id}", StageContractError)
    artifact_names = {
        _normalized_name(name)
        for artifact in artifacts for name in (artifact.artifact_id, *artifact.aliases)
    }
    stage_names = {
        _normalized_name(name)
        for stage in stages for name in (stage.stage_id, *stage.aliases)
    }
    overlap = artifact_names & stage_names
    if overlap:
        raise TypeRegistryError(f"artifact/stage 标识或别名冲突：{sorted(overlap)}")
    allowed = set(amap) | set(external)
    stage_graph = {}
    for sid, stage in smap.items():
        _status(stage.status, f"stage {sid}.status", StageContractError)
        _boolean(stage.confirmation_required, f"stage {sid}.confirmation_required", StageContractError)
        deps = _strings(stage.depends_on, f"stage {sid}.depends_on", StageContractError)
        if set(deps) - set(smap):
            raise StageContractError(f"stage {sid} 引用未知阶段：{sorted(set(deps) - set(smap))}")
        stage_graph[sid] = deps
        for key in ("consumes_artifact_ids", "produces_artifact_ids", "validates_artifact_ids"):
            refs = _strings(getattr(stage, key), f"stage {sid}.{key}", StageContractError)
            if set(refs) - allowed:
                raise StageContractError(f"stage {sid} 引用未知 artifact：{sorted(set(refs) - allowed)}")
            if key == "produces_artifact_ids":
                for aid in refs:
                    if aid not in amap or amap[aid].production_stage != sid or amap[aid].origin != "workflow_output":
                        raise StageContractError(f"stage {sid} 与 artifact {aid} 的 producer 不一致")
            if key == "validates_artifact_ids":
                for aid in refs:
                    if aid in amap and sid not in amap[aid].validation_stages:
                        raise StageContractError(f"stage {sid} 与 artifact {aid} 的 validator 不一致")
    _acyclic(stage_graph, "stage", StageContractError)
    artifact_graph = {}
    for aid, artifact in amap.items():
        _status(artifact.status, f"artifact {aid}.status", ArtifactContractError)
        forms = _strings(artifact.delivery_forms, f"artifact {aid}.delivery_forms", ArtifactContractError, empty=False)
        if set(forms) - set(pack.delivery_forms):
            raise ArtifactContractError(f"artifact {aid} 的 delivery_form 不属于 type pack")
        deps = _strings(artifact.depends_on, f"artifact {aid}.depends_on", ArtifactContractError)
        if set(deps) - allowed:
            raise ArtifactContractError(f"artifact {aid} 引用未知 artifact dependency")
        artifact_graph[aid] = tuple(d for d in deps if d in amap)
        for value, registered, label in ((artifact.validator, pack.validators, "validator"),
                                          (artifact.exporter, pack.exporters, "exporter")):
            if value is not None and value not in registered:
                raise ArtifactContractError(f"artifact {aid} 的 {label} 未注册：{value!r}")
        if artifact.origin == "user_input":
            if artifact.production_stage is not None or artifact.input_stage not in smap:
                raise ArtifactContractError(f"artifact {aid} 必须是无 producer 的已声明用户输入")
            if aid not in smap[artifact.input_stage].consumes_artifact_ids:
                raise StageContractError(f"stage {artifact.input_stage} 必须消费用户输入 {aid}")
        elif artifact.origin == "workflow_output":
            if artifact.input_stage is not None or artifact.production_stage not in smap:
                raise ArtifactContractError(f"artifact {aid} 必须有已声明的 production_stage")
            if aid not in smap[artifact.production_stage].produces_artifact_ids:
                raise StageContractError(f"stage {artifact.production_stage} 必须产出 {aid}")
        else:
            raise ArtifactContractError(f"artifact {aid} 的 origin 无效")
        for sid in _strings(artifact.validation_stages, f"artifact {aid}.validation_stages", ArtifactContractError):
            if sid not in smap or aid not in smap[sid].validates_artifact_ids:
                raise StageContractError(f"artifact {aid} 的 validation_stage {sid!r} 不一致")
            if artifact.production_stage is not None and artifact.production_stage not in _upstream(smap, sid):
                raise StageContractError(f"artifact {aid} 的验证必须位于 production_stage 之后")
    _acyclic(artifact_graph, "artifact", ArtifactContractError)


def _validate_stage_runtime(pack: TypePackDescriptor, stage: StageContract) -> None:
    if pack.contract_schema == "legacy":
        return
    label = f"stage {stage.stage_id}"
    if stage.stage_type not in STAGE_TYPES:
        raise StageContractError(
            f"type pack {pack.medium_id}.{label}.stage_type 无效：{stage.stage_type!r}"
        )
    _text(stage.owner, f"type pack {pack.medium_id}.{label}.owner", StageContractError)
    _text(stage.gate, f"type pack {pack.medium_id}.{label}.gate", StageContractError)


def validate_type_contract(pack: TypePackDescriptor) -> TypePackDescriptor:
    _id(pack.medium_id, "type pack.medium_id")
    _status(pack.status, f"type pack {pack.medium_id}.status", TypeRegistryError)
    _text(pack.version, f"type pack {pack.medium_id}.version")
    _text(pack.workflow_policy, f"type pack {pack.medium_id}.workflow_policy")
    _strings(pack.delivery_forms, "type pack.delivery_forms", empty=False)
    for name in ("aliases", "legacy_aliases", "validators", "exporters", "capabilities"):
        _strings(getattr(pack, name), f"type pack.{name}")
    if pack.contract_schema == "legacy":
        _index(pack.artifact_types, "artifact_id", "legacy artifact", ArtifactContractError)
        if pack.status == "active" and not pack.artifact_types:
            raise TypeRegistryError(f"type pack {pack.medium_id} 不允许空 active 包")
        return pack
    if pack.contract_schema != "type-pack-contract-v1":
        raise TypeRegistryError("未知 type pack contract schema")
    if pack.status == "active" and (not pack.artifact_types or not pack.stages):
        raise TypeRegistryError(f"type pack {pack.medium_id} 的 active v1 包必须有核心产物和阶段")
    for stage in pack.stages:
        _validate_stage_runtime(pack, stage)
    _validate_scope(pack, pack.artifact_types, pack.stages)
    if pack.status == "active" and any(stage.status != "active" for stage in pack.stages):
        raise StageContractError(f"type pack {pack.medium_id} 的必需核心阶段必须全部 active")
    if pack.status == "active" and not any(
        a.origin == "workflow_output" and a.status == "active" and
        resolve_stage(pack, a.production_stage).status == "active"
        for a in pack.artifact_types
    ):
        raise TypeRegistryError(f"type pack {pack.medium_id} 缺少可执行核心目标")
    core_artifacts, core_stages = set(pack.artifact_ids), {s.stage_id for s in pack.stages}
    workflow_names, all_artifacts = set(), set(core_artifacts)
    for workflow in pack.optional_workflows:
        _id(workflow.workflow_id, "workflow.workflow_id", WorkflowContractError)
        for name in {workflow.workflow_id, _text(workflow.trigger_intent, "workflow.trigger_intent", WorkflowContractError)}:
            key = _normalized_name(name)
            if key in workflow_names:
                raise WorkflowContractError(f"workflow 标识/意图冲突：{name!r}")
            workflow_names.add(key)
        if type(workflow.required) is not bool or type(workflow.blocks_core_completion) is not bool:
            raise WorkflowContractError("workflow.required/blocks_core_completion 必须是布尔值")
        if workflow.required or workflow.blocks_core_completion:
            raise WorkflowContractError(f"optional workflow {workflow.workflow_id} 不得阻塞 core completion")
        inputs = set()
        for requirement in workflow.inputs:
            _text(requirement.required_status, "workflow input.required_status", WorkflowContractError)
            if requirement.artifact_id not in core_artifacts or requirement.artifact_id in inputs:
                raise WorkflowContractError(f"workflow {workflow.workflow_id} 输入引用无效：{requirement.artifact_id}")
            inputs.add(requirement.artifact_id)
        if not workflow.stages or not workflow.artifact_types:
            raise WorkflowContractError(f"workflow {workflow.workflow_id} 缺少产物/阶段")
        if core_stages & {s.stage_id for s in workflow.stages}:
            raise StageContractError(f"workflow {workflow.workflow_id} 阶段混入 core")
        workflow_artifacts = {a.artifact_id for a in workflow.artifact_types}
        if all_artifacts & workflow_artifacts:
            raise ArtifactContractError(f"workflow {workflow.workflow_id} 产物与 core/其他 workflow 冲突")
        all_artifacts.update(workflow_artifacts)
        for stage in workflow.stages:
            _validate_stage_runtime(pack, stage)
        _validate_scope(pack, workflow.artifact_types, workflow.stages, inputs)
    return pack


def parse_type_registry(payload: Any) -> TypeRegistry:
    _object(payload, {"schema_version", "packs"}, set(), "registry", TypeRegistryError)
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise TypeRegistryError("不支持的 type registry schema_version")
    if not isinstance(payload["packs"], list) or not payload["packs"]:
        raise TypeRegistryError("type packs 不得为空")
    packs = []
    for index, raw in enumerate(payload["packs"]):
        label = f"type pack[{index}]"
        _object(raw, _PACK_REQUIRED, _PACK_OPTIONAL, label, TypeRegistryError)
        artifacts = raw["artifact_types"]
        if not isinstance(artifacts, list):
            raise ArtifactContractError(f"{label}.artifact_types 必须是数组")
        legacy = (bool(artifacts) and all(isinstance(a, str) for a in artifacts) and
                  not raw.get("stages") and not raw.get("optional_workflows"))
        old_planned = not artifacts and not (set(raw) & {"version", "stages", "optional_workflows"})
        if legacy or old_planned:
            artifacts = tuple(ArtifactDescriptor(artifact_id=_id(a, "legacy artifact", ArtifactContractError))
                              for a in _strings(artifacts, "legacy artifact", ArtifactContractError))
            schema = "legacy"
        else:
            artifacts = _objects(artifacts, f"{label}.artifacts", _parse_artifact, ArtifactContractError)
            schema = "type-pack-contract-v1"
            if "version" not in raw:
                raise TypeRegistryError(f"{label}.version 必须显式提供")
        pack = TypePackDescriptor(
            medium_id=_id(raw["medium_id"], f"{label}.medium_id"),
            aliases=_strings(raw["aliases"], f"{label}.aliases"),
            delivery_forms=_strings(raw["delivery_forms"], f"{label}.delivery_forms", empty=False),
            artifact_types=artifacts,
            workflow_policy=_text(raw["workflow_policy"], f"{label}.workflow_policy"),
            status=_status(raw["status"], f"{label}.status", TypeRegistryError),
            legacy_aliases=_strings(raw.get("legacy_aliases", []), f"{label}.legacy_aliases"),
            version=_text(raw.get("version", "legacy-v1"), f"{label}.version"),
            stages=_objects(raw.get("stages", []), f"{label}.stages", _parse_stage, StageContractError),
            validators=_strings(raw.get("validators", []), f"{label}.validators"),
            exporters=_strings(raw.get("exporters", []), f"{label}.exporters"),
            capabilities=_strings(raw.get("capabilities", []), f"{label}.capabilities"),
            optional_workflows=_objects(raw.get("optional_workflows", []), f"{label}.workflows", _parse_workflow, WorkflowContractError),
            contract_schema=schema,
        )
        packs.append(validate_type_contract(pack))
    type_names = set()
    for pack in packs:
        for name in (pack.medium_id, *pack.aliases, *pack.legacy_aliases):
            key = _normalized_name(name)
            if key in type_names:
                raise TypeRegistryError(f"type pack 标识冲突：{name!r}")
            type_names.add(key)
    for pack in packs:
        scopes = [(pack.artifact_types, pack.stages)] + [(w.artifact_types, w.stages) for w in pack.optional_workflows]
        for artifacts, stages in scopes:
            for item in (*artifacts, *stages):
                for alias in item.aliases:
                    if _normalized_name(alias) in type_names:
                        raise TypeRegistryError(f"artifact/stage alias 遮蔽 type 标识：{alias!r}")
    return TypeRegistry(tuple(packs))


def load_type_registry(path: str | Path | None = None) -> TypeRegistry:
    source = Path(path) if path is not None else _REGISTRY_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise TypeRegistryError(f"无法读取 type registry：{source}") from error
    return parse_type_registry(payload)


def _resolve(items, identifier, id_field, error, label, aliases=True):
    key = _normalized_name(_text(identifier, f"{label} identifier", error))
    for item in items:
        names = (getattr(item, id_field), *item.aliases) if aliases else (item.workflow_id, item.trigger_intent)
        if any(_normalized_name(name) == key for name in names):
            return item
    raise error(f"未知 {label}：{identifier!r}")


def resolve_type_pack(registry: TypeRegistry, identifier: str) -> TypePackDescriptor:
    key = _normalized_name(_text(identifier, "type identifier"))
    for pack in registry.packs:
        if any(_normalized_name(n) == key for n in (pack.medium_id, *pack.aliases, *pack.legacy_aliases)):
            return pack
    raise TypeRegistryError(f"未知 medium_id：{identifier!r}")


def resolve_artifact(type_pack: TypePackDescriptor, identifier: str) -> ArtifactDescriptor:
    return _resolve(type_pack.artifact_types, identifier, "artifact_id", ArtifactContractError, "core artifact")


def resolve_workflow_artifact(workflow: WorkflowContract, identifier: str) -> ArtifactDescriptor:
    return _resolve(workflow.artifact_types, identifier, "artifact_id", ArtifactContractError, "workflow artifact")


def resolve_stage(workflow: TypePackDescriptor | WorkflowContract, identifier: str) -> StageContract:
    return _resolve(workflow.stages, identifier, "stage_id", StageContractError, "stage")


def resolve_workflow(type_pack: TypePackDescriptor, identifier: str) -> WorkflowContract:
    return _resolve(type_pack.optional_workflows, identifier, "workflow_id", WorkflowContractError, "workflow", aliases=False)


def assert_type_pack_executable(type_pack: TypePackDescriptor) -> None:
    if type_pack.status != "active" or type_pack.contract_schema != "type-pack-contract-v1":
        raise TypePackNotExecutableError(f"type pack {type_pack.medium_id!r} 当前不可执行（{type_pack.status}/{type_pack.contract_schema}）")
    validate_type_contract(type_pack)


def assert_core_artifact_target(type_pack: TypePackDescriptor, artifact_id: str) -> ArtifactDescriptor:
    artifact = resolve_artifact(type_pack, artifact_id)
    if artifact.origin != "workflow_output" or artifact.status != "active" or artifact.production_stage is None:
        raise ArtifactContractError(f"artifact {artifact.artifact_id} 不是 active 核心产出目标")
    producer = resolve_stage(type_pack, artifact.production_stage)
    if producer.status != "active" or artifact.artifact_id not in producer.produces_artifact_ids:
        raise ArtifactContractError(f"artifact {artifact.artifact_id} 缺少 active producer")
    return artifact


@lru_cache(maxsize=1)
def default_type_registry() -> TypeRegistry:
    return load_type_registry()


def canonical_medium_id(identifier: str) -> str:
    return resolve_type_pack(default_type_registry(), identifier).medium_id
