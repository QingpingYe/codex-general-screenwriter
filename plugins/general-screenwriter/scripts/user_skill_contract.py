"""Legacy user skill registry contract (deprecated).

Superseded by skills/user-skill-hub/scripts/user_skill_hub.py; this module is
removed by the 2026-10-12 user-skill-hub follow-up migration.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


STATUSES = {"draft", "active", "disabled", "retired"}
SKILL_TYPES = {"prompt_skill", "checklist_skill", "validator_skill", "exporter_skill"}
EXECUTION_POLICIES = {"dialog_only", "advisory", "blocking_validator", "export_only", "interactive"}
ALLOWED_PRECEDENCE = {"series_skill", "project_skill", "user_experiment"}
SCOPE_TYPES = {
    "global", "medium", "genre", "series", "project",
    "season", "episode", "scene", "task",
}

_REQUIRED_FIELDS = {
    "skill_id", "version", "title", "description", "author", "owner",
    "status", "created_at", "updated_at", "skill_type", "scopes",
    "allowed_stages", "input_contract", "output_contract", "depends_on",
    "conflicts_with", "precedence", "execution_policy", "content_refs", "audit",
}


class UserSkillContractError(ValueError):
    pass


@dataclass(frozen=True)
class UserSkillDescriptor:
    skill_id: str
    version: str
    title: str
    description: str
    author: str
    owner: str
    status: str
    created_at: str
    updated_at: str
    skill_type: str
    scopes: tuple[Mapping[str, Any], ...]
    allowed_stages: tuple[str, ...]
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    depends_on: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    precedence: str
    execution_policy: str
    content_refs: tuple[str, ...]
    audit: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class UserSkillRegistry:
    skills: tuple[UserSkillDescriptor, ...]


def parse_user_skill_registry(payload: Any) -> UserSkillRegistry:
    if (not isinstance(payload, Mapping)
            or not {"skills"} <= set(payload) <= {"schema_version", "skills"}
            or not isinstance(payload["skills"], list)
            or not payload["skills"]):
        raise UserSkillContractError("用户技能注册表必须是包含非空 skills 数组的对象")
    if "schema_version" in payload and payload["schema_version"] != 1:
        raise UserSkillContractError("不支持的用户技能注册表 schema_version")
    skills = [descriptor_from_dict(raw, f"skills[{index}]")
              for index, raw in enumerate(payload["skills"])]
    for skill in skills:
        if skill.status != "active":
            raise UserSkillContractError(
                f"{skill.skill_id}: 解析注册表只接受 active 技能，当前状态 {skill.status}"
            )
    seen_versions = set()
    seen_ids = set()
    for skill in skills:
        if (skill.skill_id, skill.version) in seen_versions:
            raise UserSkillContractError(
                f"{skill.skill_id}: 版本 {skill.version} 重复"
            )
        if skill.skill_id in seen_ids:
            raise UserSkillContractError(
                f"{skill.skill_id}: 注册表内同一 skill_id 只能有一个 active 版本"
            )
        seen_versions.add((skill.skill_id, skill.version))
        seen_ids.add(skill.skill_id)
    return UserSkillRegistry(skills=tuple(skills))


def load_user_skill_registry(path: str | Path) -> UserSkillRegistry:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise UserSkillContractError(f"无法读取用户技能注册表：{source}") from error
    return parse_user_skill_registry(payload)


def descriptor_from_dict(payload: Any, label: str = "skill") -> UserSkillDescriptor:
    _object(payload, _REQUIRED_FIELDS, label)
    error = UserSkillContractError
    descriptor = UserSkillDescriptor(
        skill_id=_text(payload["skill_id"], f"{label}.skill_id"),
        version=_text(payload["version"], f"{label}.version"),
        title=_text(payload["title"], f"{label}.title"),
        description=_text(payload["description"], f"{label}.description"),
        author=_text(payload["author"], f"{label}.author"),
        owner=_text(payload["owner"], f"{label}.owner"),
        status=_enum(payload["status"], STATUSES, f"{label}.status"),
        created_at=_text(payload["created_at"], f"{label}.created_at"),
        updated_at=_text(payload["updated_at"], f"{label}.updated_at"),
        skill_type=_enum(payload["skill_type"], SKILL_TYPES, f"{label}.skill_type"),
        scopes=_scopes(payload["scopes"], f"{label}.scopes"),
        allowed_stages=_strings(payload["allowed_stages"], f"{label}.allowed_stages", allow_empty=False),
        input_contract=_object(payload["input_contract"], set(), f"{label}.input_contract", allow_any_keys=True),
        output_contract=_object(payload["output_contract"], set(), f"{label}.output_contract", allow_any_keys=True),
        depends_on=_strings(payload["depends_on"], f"{label}.depends_on"),
        conflicts_with=_strings(payload["conflicts_with"], f"{label}.conflicts_with"),
        precedence=_enum(payload["precedence"], ALLOWED_PRECEDENCE, f"{label}.precedence"),
        execution_policy=_enum(payload["execution_policy"], EXECUTION_POLICIES, f"{label}.execution_policy"),
        content_refs=_strings(payload["content_refs"], f"{label}.content_refs", allow_empty=False),
        audit=_audit(payload["audit"], f"{label}.audit"),
    )
    if descriptor.precedence in {"system_skill", "type_pack_skill"}:
        raise error(f"{label}.precedence 不能达到或高于 system 权威")
    return descriptor


def descriptor_to_dict(descriptor: UserSkillDescriptor) -> dict[str, Any]:
    return {
        "skill_id": descriptor.skill_id,
        "version": descriptor.version,
        "title": descriptor.title,
        "description": descriptor.description,
        "author": descriptor.author,
        "owner": descriptor.owner,
        "status": descriptor.status,
        "created_at": descriptor.created_at,
        "updated_at": descriptor.updated_at,
        "skill_type": descriptor.skill_type,
        "scopes": [dict(scope) for scope in descriptor.scopes],
        "allowed_stages": list(descriptor.allowed_stages),
        "input_contract": dict(descriptor.input_contract),
        "output_contract": dict(descriptor.output_contract),
        "depends_on": list(descriptor.depends_on),
        "conflicts_with": list(descriptor.conflicts_with),
        "precedence": descriptor.precedence,
        "execution_policy": descriptor.execution_policy,
        "content_refs": list(descriptor.content_refs),
        "audit": [dict(entry) for entry in descriptor.audit],
    }


def validate_user_skill_descriptor(
    descriptor: UserSkillDescriptor, type_pack: Any
) -> UserSkillDescriptor:
    if not isinstance(descriptor, UserSkillDescriptor):
        raise UserSkillContractError("descriptor must be a UserSkillDescriptor")
    if descriptor.status != "active":
        raise UserSkillContractError(
            f"{descriptor.skill_id}: 只有 active 技能可进入解析，当前状态 {descriptor.status}"
        )
    pack_stages = {stage.stage_id for stage in getattr(type_pack, "stages", ())}
    for workflow in getattr(type_pack, "optional_workflows", ()):
        pack_stages.update(stage.stage_id for stage in workflow.stages)
    unknown = [stage for stage in descriptor.allowed_stages if stage not in pack_stages]
    if unknown:
        raise UserSkillContractError(
            f"{descriptor.skill_id}: allowed_stages 引用未知阶段：{', '.join(unknown)}"
        )
    medium_id = getattr(type_pack, "medium_id", None)
    for ref in (*descriptor.depends_on, *descriptor.conflicts_with):
        if ref.startswith("type_pack:") and not ref.startswith(f"type_pack:{medium_id}:"):
            raise UserSkillContractError(
                f"{descriptor.skill_id}: 引用不属于当前类型包 {medium_id}：{ref}"
            )
    return descriptor


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UserSkillContractError(f"{label} 必须是非空字符串")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise UserSkillContractError(f"{label} 必须是 {sorted(allowed)} 之一")
    return value


def _strings(value: Any, label: str, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise UserSkillContractError(f"{label} 必须是非空字符串数组")
    if not allow_empty and not value:
        raise UserSkillContractError(f"{label} 不得为空")
    return tuple(value)


def _object(value: Any, required: set[str], label: str, allow_any_keys: bool = False) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UserSkillContractError(f"{label} 必须是对象")
    if not required <= set(value):
        raise UserSkillContractError(f"{label} 缺少必填字段")
    if not allow_any_keys and not set(value) <= required:
        raise UserSkillContractError(f"{label} 包含未知字段")
    return dict(value)


def _scopes(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise UserSkillContractError(f"{label} 必须是非空数组")
    scopes = []
    for index, raw in enumerate(value):
        scope_label = f"{label}[{index}]"
        if not isinstance(raw, Mapping) or "scope_type" not in raw:
            raise UserSkillContractError(f"{scope_label} 必须包含 scope_type")
        scope_type = raw["scope_type"]
        if scope_type not in SCOPE_TYPES:
            raise UserSkillContractError(f"{scope_label}.scope_type 未知：{scope_type}")
        identifiers = [key for key in raw if key != "scope_type"]
        if not identifiers or any(not isinstance(raw[key], str) or not raw[key].strip() for key in identifiers):
            raise UserSkillContractError(f"{scope_label} 至少需要一个非空作用域标识")
        scopes.append(dict(raw))
    return tuple(scopes)


def _audit(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise UserSkillContractError(f"{label} 必须是非空数组")
    entries = []
    for index, raw in enumerate(value):
        if (not isinstance(raw, Mapping)
                or not isinstance(raw.get("action"), str) or not raw["action"].strip()
                or not isinstance(raw.get("at"), str) or not raw["at"].strip()):
            raise UserSkillContractError(f"{label}[{index}] 需要 action 与 at 字段")
        entries.append(dict(raw))
    return tuple(entries)
