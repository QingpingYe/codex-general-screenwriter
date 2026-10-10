"""Validation for lightweight user skill packs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from type_registry import TypeRegistry, load_type_registry


SUPPORT_FIELDS: tuple[str, ...] = (
    "medium_ids", "genre_ids", "series_ids", "project_ids", "stage_ids",
    "artifact_ids",
)
SKILL_TYPES = {"prompt_skill", "checklist_skill", "reference_skill", "exporter_skill"}
_MANIFEST_FIELDS = {
    "schema_version", "skill_id", "title", "description", "user_name",
    "skill_type", "supports", "content", "updated_at",
}
_REQUIRED_TEXT_FIELDS = ("skill_id", "title", "description", "user_name", "content")
_CONTENT_FILE = "SKILL.md"


class UserSkillHubError(ValueError):
    """Invalid lightweight user skill manifest or skill pack."""


@dataclass(frozen=True)
class UserSkill:
    directory: Path
    manifest: dict[str, Any]
    content: str


def _load_type_registry(plugin_root: Path) -> TypeRegistry:
    try:
        return load_type_registry(plugin_root / "config" / "type-packs.json")
    except ValueError as error:
        raise UserSkillHubError(f"无法读取 type registry：{plugin_root}") from error


def _load_manifest(directory: Path) -> dict[str, Any]:
    path = directory / "manifest.json"
    if not path.is_file():
        raise UserSkillHubError(f"{directory}: 缺少 manifest.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UserSkillHubError(f"{directory}: manifest.json 不是有效 JSON") from error
    if not isinstance(payload, dict):
        raise UserSkillHubError(f"{directory}: manifest.json 必须是对象")
    return payload


def _validate_supports(manifest: dict[str, Any], label: str) -> dict[str, Any]:
    supports = manifest["supports"]
    if not isinstance(supports, dict):
        raise UserSkillHubError(f"{label}.supports 必须是对象")
    if set(supports) != set(SUPPORT_FIELDS):
        raise UserSkillHubError(
            f"{label}.supports 字段必须是 {', '.join(SUPPORT_FIELDS)}"
        )
    for field in SUPPORT_FIELDS:
        values = supports[field]
        if not isinstance(values, list) or not values:
            raise UserSkillHubError(f"{label}.supports.{field} 必须是非空字符串数组")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise UserSkillHubError(f"{label}.supports.{field} 必须是非空字符串数组")
        if len(set(values)) != len(values):
            raise UserSkillHubError(f"{label}.supports.{field} 不得重复")
        if "all" in values and len(values) != 1:
            raise UserSkillHubError(f"{label}.supports.{field} 不得混用 all")
    return supports


def _validate_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise UserSkillHubError(f"{label} 必须是带时区的 ISO 8601 时间")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise UserSkillHubError(f"{label} 必须是带时区的 ISO 8601 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UserSkillHubError(f"{label} 必须带时区")


def _selected_type_packs(
    registry: TypeRegistry, medium_ids: list[str], label: str
):
    active_packs = {
        pack.medium_id: pack for pack in registry.packs if pack.status == "active"
    }
    if medium_ids == ["all"]:
        packs = tuple(active_packs.values())
        if not packs:
            raise UserSkillHubError(f"{label}.supports.medium_ids 没有 active 类型包")
        return packs
    packs = []
    for medium_id in medium_ids:
        pack = active_packs.get(medium_id)
        if pack is None:
            raise UserSkillHubError(
                f"{label}.supports.medium_ids 必须是 canonical active medium_id，"
                f"当前无效：{medium_id}"
            )
        packs.append(pack)
    return tuple(packs)


def _validate_type_references(
    packs, stage_ids: list[str], artifact_ids: list[str], label: str
) -> None:
    for field, values, kind in (
        ("stage_ids", stage_ids, "stage"),
        ("artifact_ids", artifact_ids, "artifact"),
    ):
        if values == ["all"]:
            continue
        for value in values:
            missing = []
            for pack in packs:
                if kind == "stage":
                    available = {stage.stage_id for stage in pack.stages}
                    available.update(
                        stage.stage_id
                        for workflow in pack.optional_workflows
                        for stage in workflow.stages
                    )
                else:
                    available = {
                        artifact.artifact_id for artifact in pack.artifact_types
                    }
                    available.update(
                        artifact.artifact_id
                        for workflow in pack.optional_workflows
                        for artifact in workflow.artifact_types
                    )
                if value not in available:
                    missing.append(pack.medium_id)
            if missing:
                raise UserSkillHubError(
                    f"{label}.supports.{field} 在类型包 {', '.join(missing)} 中不存在：{value}"
                )


def _validate_content(directory: Path, value: Any, label: str) -> str:
    if value != _CONTENT_FILE:
        raise UserSkillHubError(f"{label}.content 必须是 {_CONTENT_FILE}")
    path = directory / _CONTENT_FILE
    if not path.is_file() or path.is_symlink():
        raise UserSkillHubError(f"{label}.content 指向的文件不存在：{value}")
    try:
        if not path.read_text(encoding="utf-8-sig").strip():
            raise UserSkillHubError(f"{label}.content 文件不得为空：{_CONTENT_FILE}")
    except (OSError, UnicodeError) as error:
        raise UserSkillHubError(f"{label}.content 文件无法读取：{_CONTENT_FILE}") from error
    return value


def _reject_extra_files(directory: Path, label: str) -> None:
    allowed_files = {directory / "manifest.json", directory / _CONTENT_FILE}
    for path in directory.rglob("*"):
        if path in allowed_files and path.is_file() and not path.is_symlink():
            continue
        raise UserSkillHubError(f"{label} 只能包含 manifest.json 与 content 文件：{path.name}")


def _validate_user_skill(
    directory: Path, registry: TypeRegistry
) -> UserSkill:
    directory = directory.resolve()
    if not directory.is_dir():
        raise UserSkillHubError(f"用户技能目录不存在：{directory}")
    label = directory.name
    manifest = _load_manifest(directory)
    if set(manifest) != _MANIFEST_FIELDS:
        missing = sorted(_MANIFEST_FIELDS - set(manifest))
        unknown = sorted(set(manifest) - _MANIFEST_FIELDS)
        details = []
        if missing:
            details.append(f"缺少字段：{', '.join(missing)}")
        if unknown:
            details.append(f"未知字段：{', '.join(unknown)}")
        raise UserSkillHubError(f"{label}: {'；'.join(details)}")

    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise UserSkillHubError(f"{label}: schema_version 必须是 1")
    for field in _REQUIRED_TEXT_FIELDS:
        value = manifest[field]
        if not isinstance(value, str) or not value.strip():
            raise UserSkillHubError(f"{label}.{field} 必须是非空字符串")
    if manifest["skill_id"] != label:
        raise UserSkillHubError(
            f"{label}: skill_id 必须与目录名一致，当前为 {manifest['skill_id']}"
        )
    if manifest["skill_type"] not in SKILL_TYPES:
        raise UserSkillHubError(f"{label}: 未知 skill_type：{manifest['skill_type']}")
    _validate_timestamp(manifest["updated_at"], f"{label}.updated_at")

    supports = _validate_supports(manifest, label)
    packs = _selected_type_packs(registry, supports["medium_ids"], label)
    _validate_type_references(
        packs, supports["stage_ids"], supports["artifact_ids"], label
    )

    content = _validate_content(directory, manifest["content"], label)
    _reject_extra_files(directory, label)
    return UserSkill(directory=directory, manifest=manifest, content=content)


def validate_user_skill(skill_dir: Path, plugin_root: Path) -> UserSkill:
    registry = _load_type_registry(Path(plugin_root).resolve())
    return _validate_user_skill(Path(skill_dir), registry)


def validate_user_skill_tree(plugin_root: Path) -> tuple[UserSkill, ...]:
    root = Path(plugin_root).resolve()
    registry = _load_type_registry(root)
    user_skills = root / "skills" / "user-skills"
    if not user_skills.exists():
        return ()
    if not user_skills.is_dir():
        raise UserSkillHubError(f"用户技能目录必须是目录：{user_skills}")
    directories = sorted(
        directory for directory in user_skills.iterdir() if directory.is_dir()
    )
    seen_skill_ids: dict[str, Path] = {}
    for directory in directories:
        manifest = _load_manifest(directory)
        skill_id = manifest.get("skill_id")
        if isinstance(skill_id, str):
            previous = seen_skill_ids.get(skill_id)
            if previous is not None:
                raise UserSkillHubError(
                    f"重复 skill_id：{skill_id}（{previous.name}，{directory.name}）"
                )
            seen_skill_ids[skill_id] = directory
    return tuple(
        _validate_user_skill(directory, registry)
        for directory in directories
    )
