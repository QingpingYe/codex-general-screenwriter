import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
for path in (str(ROOT / "scripts"),):
    if path not in sys.path:
        sys.path.insert(0, path)

from type_registry import load_type_registry, resolve_type_pack
from user_skill_contract import (
    UserSkillContractError,
    UserSkillDescriptor,
    descriptor_from_dict,
    descriptor_to_dict,
    load_user_skill_registry,
    parse_user_skill_registry,
    validate_user_skill_descriptor,
)


CONTRACT = ROOT / "config" / "plugin-contract.json"
EXAMPLE = ROOT / "config" / "user-skills.example.json"


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
        "output_contract": {"kind": "checklist"},
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
    registry = load_type_registry()
    return resolve_type_pack(registry, "picturebook")


class ParseRegistryTests(unittest.TestCase):
    def test_rejects_draft_skill_in_active_resolution_scope(self):
        with self.assertRaises(UserSkillContractError):
            parse_user_skill_registry({"skills": [skill_payload(status="draft")]})

    def test_rejects_duplicate_skill_versions(self):
        payload = skill_payload()
        with self.assertRaises(UserSkillContractError):
            parse_user_skill_registry({"skills": [payload, dict(payload)]})

    def test_parse_returns_active_descriptors(self):
        registry = parse_user_skill_registry({"skills": [skill_payload()]})
        self.assertEqual(len(registry.skills), 1)
        self.assertEqual(registry.skills[0].skill_id, "project-hook-checklist")


class DescriptorTests(unittest.TestCase):
    def test_rejects_retired_skill_reactivation(self):
        descriptor = descriptor_from_dict(skill_payload(status="retired"))
        with self.assertRaises(UserSkillContractError):
            validate_user_skill_descriptor(descriptor, picturebook_pack())

    def test_rejects_precedence_above_system(self):
        with self.assertRaises(UserSkillContractError):
            descriptor_from_dict(skill_payload(precedence="system_skill"))

    def test_rejects_empty_scopes(self):
        with self.assertRaises(UserSkillContractError):
            descriptor_from_dict(skill_payload(scopes=[]))

    def test_rejects_invalid_content_refs(self):
        with self.assertRaises(UserSkillContractError):
            descriptor_from_dict(skill_payload(content_refs=[""]))

    def test_rejects_missing_audit(self):
        with self.assertRaises(UserSkillContractError):
            descriptor_from_dict(skill_payload(audit=[]))

    def test_descriptor_round_trip(self):
        descriptor = descriptor_from_dict(skill_payload())
        restored = descriptor_from_dict(descriptor_to_dict(descriptor))
        self.assertEqual(restored, descriptor)


class ValidateDescriptorTests(unittest.TestCase):
    def test_rejects_unknown_stage(self):
        descriptor = descriptor_from_dict(skill_payload(allowed_stages=["nonexistent_stage"]))
        with self.assertRaises(UserSkillContractError):
            validate_user_skill_descriptor(descriptor, picturebook_pack())

    def test_rejects_cross_pack_references(self):
        descriptor = descriptor_from_dict(
            skill_payload(depends_on=["type_pack:shortdrama:quality_rules"]))
        with self.assertRaises(UserSkillContractError):
            validate_user_skill_descriptor(descriptor, picturebook_pack())

    def test_accepts_project_scoped_skill_for_picturebook(self):
        descriptor = descriptor_from_dict(skill_payload())
        validated = validate_user_skill_descriptor(descriptor, picturebook_pack())
        self.assertEqual(validated.skill_id, "project-hook-checklist")


class ExampleRegistryTests(unittest.TestCase):
    def test_example_registry_loads_and_validates(self):
        registry = load_user_skill_registry(EXAMPLE)
        pack = picturebook_pack()
        for skill in registry.skills:
            with self.subTest(skill=skill.skill_id):
                validate_user_skill_descriptor(skill, pack)


if __name__ == "__main__":
    unittest.main()
