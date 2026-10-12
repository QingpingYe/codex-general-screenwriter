"""Legacy user skill resolver (deprecated).

Superseded by skills/user-skill-hub/scripts/user_skill_hub.py; removed by the
2026-10-12 user-skill-hub follow-up migration.
"""

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SCRIPTS = Path(__file__).resolve().parent
LOADER_SCRIPTS = SCRIPTS.parent.parent / "skills" / "knowledge-loader" / "scripts"
for path in (str(LOADER_SCRIPTS),):
    if path not in sys.path:
        sys.path.insert(0, path)

from scope_model import ScopeChainNode, expand_scope_chain, scope_matches
from user_skill_contract import (
    UserSkillDescriptor,
    UserSkillRegistry,
    descriptor_to_dict,
)


PRECEDENCE_RANK = {
    "project_skill": 0,
    "series_skill": 1,
    "user_experiment": 2,
}


@dataclass(frozen=True)
class SkillQuery:
    scope_ref: Any
    stage_id: str
    intent: str | None = None
    artifact_targets: tuple[str, ...] = ()
    include_experimental: bool = False
    exclude_skill_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillSnapshot:
    skill_id: str
    version: str
    authority: str
    scopes: tuple[Mapping[str, Any], ...]
    stage_id: str
    execution_policy: str
    status: str
    content_hash: str


@dataclass(frozen=True)
class SkillConflict:
    skill_ids: tuple[str, ...]
    reason: str
    winner: str | None = None


@dataclass(frozen=True)
class RejectedSkill:
    skill_id: str
    reason: str
    descriptor: UserSkillDescriptor


@dataclass(frozen=True)
class SkillResolution:
    matches: tuple[UserSkillDescriptor, ...]
    conflicts: tuple[SkillConflict, ...]
    rejected: tuple[RejectedSkill, ...]
    snapshot: tuple[SkillSnapshot, ...] = ()


def resolve_skills(registry, context, type_pack, query) -> SkillResolution:
    if not isinstance(registry, UserSkillRegistry):
        raise TypeError("registry must be a UserSkillRegistry")
    if not isinstance(query, SkillQuery):
        raise TypeError("query must be a SkillQuery")
    scope_ref = query.scope_ref
    if scope_ref is None:
        from knowledge_scope import build_scope_ref
        scope_ref = build_scope_ref(context)
    chain = expand_scope_chain(scope_ref)
    pack_stages = {stage.stage_id for stage in getattr(type_pack, "stages", ())}
    pack_artifacts = {artifact.artifact_id for artifact in getattr(type_pack, "artifact_types", ())}
    for workflow in getattr(type_pack, "optional_workflows", ()):
        pack_stages.update(stage.stage_id for stage in workflow.stages)
        pack_artifacts.update(artifact.artifact_id for artifact in workflow.artifact_types)
    known_ids = {skill.skill_id for skill in registry.skills}

    rejected: list[RejectedSkill] = []
    candidates: list[UserSkillDescriptor] = []
    for skill in registry.skills:
        reason = _rejection_reason(skill, query, chain, pack_stages, pack_artifacts, known_ids, type_pack)
        if reason is None:
            candidates.append(skill)
        else:
            rejected.append(RejectedSkill(skill.skill_id, reason, skill))

    matches, conflicts = _resolve_conflicts(candidates, query)
    matches.sort(key=lambda skill: (PRECEDENCE_RANK.get(skill.precedence, 99), skill.skill_id))
    snapshots = tuple(
        SkillSnapshot(
            skill_id=skill.skill_id,
            version=skill.version,
            authority=skill.precedence,
            scopes=tuple(dict(scope) for scope in skill.scopes),
            stage_id=query.stage_id,
            execution_policy=skill.execution_policy,
            status=skill.status,
            content_hash=_content_hash(skill),
        )
        for skill in matches
    )
    return SkillResolution(
        matches=tuple(matches),
        conflicts=tuple(conflicts),
        rejected=tuple(rejected),
        snapshot=snapshots,
    )


def resolution_snapshot_to_dict(resolution: SkillResolution) -> list[dict[str, Any]]:
    return [
        {
            "skill_id": item.skill_id,
            "version": item.version,
            "authority": item.authority,
            "scopes": [dict(scope) for scope in item.scopes],
            "stage_id": item.stage_id,
            "execution_policy": item.execution_policy,
            "status": item.status,
            "content_hash": item.content_hash,
        }
        for item in resolution.snapshot
    ]


def _rejection_reason(skill, query, chain, pack_stages, pack_artifacts, known_ids, type_pack) -> str | None:
    if skill.skill_id in query.exclude_skill_ids:
        return "excluded by query"
    if skill.status != "active":
        return f"status {skill.status} is not resolvable"
    if query.stage_id not in skill.allowed_stages:
        return f"stage {query.stage_id} not allowed"
    for scope in skill.scopes:
        node = _scope_node(scope)
        if node is None or not scope_matches(chain, node):
            return "scope outside current scope chain"
    if skill.precedence == "user_experiment" and not query.include_experimental:
        return "experimental skill requires explicit include"
    medium_id = getattr(type_pack, "medium_id", None)
    for ref in skill.depends_on:
        if ref.startswith("type_pack:"):
            parts = ref.split(":", 2)
            if len(parts) != 3 or parts[1] != medium_id:
                return f"dependency outside current type pack: {ref}"
            target = parts[2]
            if target not in pack_artifacts and target not in pack_stages:
                return f"dependency target missing in type pack: {ref}"
        elif ref.startswith("skill:"):
            if ref.split(":", 1)[1] not in known_ids:
                return f"dependency skill missing: {ref}"
        else:
            return f"unverifiable dependency: {ref}"
    if query.artifact_targets:
        declared = skill.output_contract.get("artifact_ids") if isinstance(skill.output_contract, Mapping) else None
        if isinstance(declared, (list, tuple)) and declared and not set(declared) & set(query.artifact_targets):
            return "artifact target not supported"
    return None


def _resolve_conflicts(candidates, query):
    matches: list[UserSkillDescriptor] = []
    conflicts: list[SkillConflict] = []
    remaining = list(candidates)

    declared_ids = {skill.skill_id for skill in remaining}
    for skill in list(remaining):
        for ref in skill.conflicts_with:
            if not ref.startswith("skill:"):
                continue
            other_id = ref.split(":", 1)[1]
            if other_id in declared_ids and other_id != skill.skill_id:
                pair = tuple(sorted((skill.skill_id, other_id)))
                if all(existing.skill_ids != pair for existing in conflicts):
                    conflicts.append(SkillConflict(
                        skill_ids=pair,
                        reason="declared conflict",
                        winner=None,
                    ))
                    remaining = [item for item in remaining if item.skill_id not in pair]
                break

    by_kind: dict[str, list[UserSkillDescriptor]] = {}
    for skill in remaining:
        kind = skill.output_contract.get("kind") if isinstance(skill.output_contract, Mapping) else None
        by_kind.setdefault(str(kind), []).append(skill)
    for kind, group in sorted(by_kind.items()):
        levels = {skill.precedence for skill in group}
        if len(levels) <= 1:
            matches.extend(group)
            continue
        best_level = min(levels, key=lambda level: PRECEDENCE_RANK.get(level, 99))
        winners = sorted(
            (skill for skill in group if skill.precedence == best_level),
            key=lambda skill: skill.skill_id,
        )
        matches.extend(winners)
        conflicts.append(SkillConflict(
            skill_ids=tuple(sorted(skill.skill_id for skill in group)),
            reason="same output target across authority levels",
            winner=winners[0].skill_id,
        ))
    return matches, conflicts


def _scope_node(scope: Mapping[str, Any]) -> ScopeChainNode | None:
    scope_type = scope.get("scope_type")
    identifier = scope.get("scope_id") or scope.get(f"{scope_type}_id")
    if not isinstance(scope_type, str) or not isinstance(identifier, str) or not identifier.strip():
        return None
    try:
        return ScopeChainNode(scope_type, identifier)
    except ValueError:
        return None


def _content_hash(skill: UserSkillDescriptor) -> str:
    payload = json.dumps(
        descriptor_to_dict(skill), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
