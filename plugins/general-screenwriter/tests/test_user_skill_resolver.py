import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PLUGIN_SCRIPTS = str(ROOT / "scripts")
LOADER_SCRIPTS = str(ROOT / "skills" / "knowledge-loader" / "scripts")
for path in (PLUGIN_SCRIPTS, LOADER_SCRIPTS):
    if path not in sys.path:
        sys.path.insert(0, path)

from scope_model import ScopeRef
from type_registry import load_type_registry, resolve_type_pack
from user_skill_contract import UserSkillRegistry, descriptor_from_dict
from user_skill_resolver import (
    SkillQuery,
    resolve_skills,
    resolution_snapshot_to_dict,
)


def skill_payload(**overrides):
    payload = {
        "skill_id": "project-hook-checklist",
        "version": "1.0.0",
        "title": "项目钩子检查清单",
        "description": "补充项目级检查项",
        "author": "user",
        "owner": "project:p1",
        "status": "active",
        "created_at": "2026-10-10T00:00:00+08:00",
        "updated_at": "2026-10-10T00:00:00+08:00",
        "skill_type": "checklist_skill",
        "scopes": [{"scope_type": "project", "project_id": "p1"}],
        "allowed_stages": ["qa"],
        "input_contract": {"artifact_ids": ["script"]},
        "output_contract": {"kind": "hook_check"},
        "depends_on": [],
        "conflicts_with": [],
        "precedence": "project_skill",
        "execution_policy": "advisory",
        "content_refs": ["skills/user/project-hook-checklist.md"],
        "audit": [{"action": "created", "at": "2026-10-10T00:00:00+08:00"}],
    }
    payload.update(overrides)
    return payload


def picturebook_pack():
    return resolve_type_pack(load_type_registry(), "picturebook")


def make_query(**overrides):
    fields = {
        "scope_ref": ScopeRef(project_id="p1", medium_id="picturebook"),
        "stage_id": "qa",
        "intent": None,
        "artifact_targets": (),
        "include_experimental": False,
        "exclude_skill_ids": (),
    }
    fields.update(overrides)
    return SkillQuery(**fields)


def resolve_with(payloads, context=None, **query_overrides):
    registry = UserSkillRegistry(
        skills=tuple(descriptor_from_dict(payload) for payload in payloads))
    return resolve_skills(
        registry, context, picturebook_pack(), make_query(**query_overrides))


class ResolveSkillsTests(unittest.TestCase):
    def test_matches_only_declared_scope_and_stage(self):
        matching = skill_payload()
        wrong_stage = skill_payload(
            skill_id="other-skill", allowed_stages=["confirmation_gate"])
        resolution = resolve_with([matching, wrong_stage])

        self.assertEqual(
            [skill.skill_id for skill in resolution.matches],
            ["project-hook-checklist"],
        )
        self.assertIn("other-skill", [item.skill_id for item in resolution.rejected])

    def test_project_skill_wins_and_series_conflict_is_reported(self):
        project_skill = skill_payload()
        series_skill = skill_payload(
            skill_id="series-hook-checklist",
            scopes=[{"scope_type": "series", "series_id": "s1"}],
            precedence="series_skill",
        )
        query = make_query()
        query_scope = ScopeRef(project_id="p1", series_id="s1", medium_id="picturebook")
        registry = UserSkillRegistry(skills=(
            descriptor_from_dict(project_skill),
            descriptor_from_dict(series_skill),
        ))
        resolution = resolve_skills(
            registry, None, picturebook_pack(),
            SkillQuery(scope_ref=query_scope, stage_id="qa"),
        )

        self.assertEqual(
            [skill.skill_id for skill in resolution.matches],
            ["project-hook-checklist"],
        )
        conflict_ids = {
            skill_id
            for conflict in resolution.conflicts
            for skill_id in conflict.skill_ids
        }
        self.assertIn("series-hook-checklist", conflict_ids)

    def test_experimental_skill_requires_explicit_include(self):
        experimental = skill_payload(
            skill_id="experiment-skill",
            precedence="user_experiment",
        )
        excluded = resolve_with([experimental])
        self.assertEqual(excluded.matches, ())
        self.assertIn(
            "experiment-skill", [item.skill_id for item in excluded.rejected])

        included = resolve_with([experimental], include_experimental=True)
        self.assertEqual(
            [skill.skill_id for skill in included.matches],
            ["experiment-skill"],
        )

    def test_disabled_skill_is_rejected(self):
        from user_skill_contract import UserSkillDescriptor  # noqa: F401
        registry = UserSkillRegistry(skills=(
            descriptor_from_dict(skill_payload(status="disabled")),
        ))
        resolution = resolve_skills(
            registry, None, picturebook_pack(), make_query())
        self.assertEqual(resolution.matches, ())
        self.assertIn("project-hook-checklist", [item.skill_id for item in resolution.rejected])

    def test_missing_dependency_is_rejected(self):
        dependent = skill_payload(
            skill_id="dependent-skill",
            depends_on=["type_pack:picturebook:not_an_object"],
        )
        resolution = resolve_with([dependent])
        self.assertEqual(resolution.matches, ())
        self.assertIn("dependent-skill", [item.skill_id for item in resolution.rejected])

    def test_declared_skill_dependency_resolves(self):
        base = skill_payload()
        dependent = skill_payload(
            skill_id="dependent-skill",
            depends_on=["skill:project-hook-checklist"],
        )
        resolution = resolve_with([base, dependent])
        self.assertEqual(
            {skill.skill_id for skill in resolution.matches},
            {"project-hook-checklist", "dependent-skill"},
        )

    def test_conflicts_do_not_merge(self):
        first = skill_payload(skill_id="skill-a")
        second = skill_payload(
            skill_id="skill-b", conflicts_with=["skill:skill-a"])
        resolution = resolve_with([first, second])

        self.assertEqual(resolution.matches, ())
        self.assertEqual(len(resolution.conflicts), 1)
        self.assertEqual(resolution.conflicts[0].skill_ids, ("skill-a", "skill-b"))

    def test_matches_order_is_deterministic(self):
        second = skill_payload(skill_id="b-skill")
        first = skill_payload(skill_id="a-skill")
        resolution = resolve_with([second, first])
        self.assertEqual(
            [skill.skill_id for skill in resolution.matches],
            ["a-skill", "b-skill"],
        )

    def test_snapshot_dicts_are_isolated_and_deterministic(self):
        resolution = resolve_with([skill_payload()])
        first = resolution_snapshot_to_dict(resolution)
        second = resolution_snapshot_to_dict(resolution)
        self.assertEqual(first, second)
        first[0]["skill_id"] = "mutated"
        self.assertEqual(
            resolution_snapshot_to_dict(resolution)[0]["skill_id"],
            "project-hook-checklist",
        )
        self.assertIn("content_hash", first[0])


if __name__ == "__main__":
    unittest.main()
