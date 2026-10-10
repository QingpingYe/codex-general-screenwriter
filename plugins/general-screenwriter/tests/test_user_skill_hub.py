import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
for path in (
    str(ROOT / "scripts"),
    str(ROOT / "skills" / "user-skill-hub" / "scripts"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

from user_skill_hub import SUPPORT_FIELDS, UserSkillHubError, validate_user_skill, validate_user_skill_tree


MISSING = object()


def valid_manifest(skill_id="test-skill", content="SKILL.md"):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "title": "Test Skill",
        "description": "A valid test skill.",
        "user_name": "张三",
        "skill_type": "prompt_skill",
        "supports": {
            "medium_ids": ["shortdrama"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["episode_design"],
            "artifact_ids": ["episode_outline"],
        },
        "content": content,
        "updated_at": "2026-10-10T00:00:00+08:00",
    }


class UserSkillHubTestCase(unittest.TestCase):
    def make_skill(self, skill_id=None, manifest_overrides=None, files=None,
                   omit_manifest=False):
        if skill_id is None:
            self._skill_counter += 1
            skill_id = f"test-skill-{self._skill_counter}"
        directory = self.temp_path / skill_id
        directory.mkdir(parents=True)
        manifest = valid_manifest(skill_id=skill_id)
        for key, value in (manifest_overrides or {}).items():
            if value is MISSING:
                manifest.pop(key, None)
            else:
                manifest[key] = value
        if not omit_manifest:
            (directory / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
        if files is None:
            files = {"SKILL.md": "Use this user skill."}
        for relative_path, text in files.items():
            path = directory / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return directory

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp.name)
        self._skill_counter = 0
        self.addCleanup(self._temp.cleanup)

    def assert_invalid(self, directory):
        with self.assertRaises(UserSkillHubError):
            validate_user_skill(directory, ROOT)


class ValidateUserSkillTests(UserSkillHubTestCase):
    def test_accepts_valid_user_skill(self):
        directory = self.make_skill(skill_id="test-skill")
        result = validate_user_skill(directory, ROOT)
        self.assertEqual(result.directory, directory.resolve())
        self.assertEqual(result.manifest["skill_id"], "test-skill")
        self.assertEqual(result.content, "SKILL.md")

    def test_missing_fields_are_rejected(self):
        for field in (
            "schema_version", "skill_id", "title", "description", "user_name",
            "skill_type", "supports", "content", "updated_at",
        ):
            with self.subTest(field=field):
                directory = self.make_skill(manifest_overrides={field: MISSING})
                self.assert_invalid(directory)

    def test_empty_support_arrays_are_rejected(self):
        for field in SUPPORT_FIELDS:
            with self.subTest(field=field):
                supports = dict(valid_manifest()["supports"])
                supports[field] = []
                directory = self.make_skill(manifest_overrides={"supports": supports})
                self.assert_invalid(directory)

    def test_all_cannot_be_mixed_with_concrete_ids(self):
        defaults = valid_manifest()["supports"]
        for field in SUPPORT_FIELDS:
            with self.subTest(field=field):
                supports = dict(defaults)
                supports[field] = ["all", "shortdrama"]
                directory = self.make_skill(manifest_overrides={"supports": supports})
                self.assert_invalid(directory)

    def test_schema_version_one_is_required(self):
        for version in (0, 2, "1", True):
            with self.subTest(version=version):
                directory = self.make_skill(manifest_overrides={"schema_version": version})
                self.assert_invalid(directory)

    def test_unknown_manifest_fields_are_rejected(self):
        directory = self.make_skill(manifest_overrides={"author": "someone"})
        self.assert_invalid(directory)

    def test_unknown_support_fields_are_rejected(self):
        supports = dict(valid_manifest()["supports"])
        supports["role_ids"] = ["all"]
        directory = self.make_skill(manifest_overrides={"supports": supports})
        self.assert_invalid(directory)

    def test_invalid_skill_type_is_rejected(self):
        directory = self.make_skill(manifest_overrides={"skill_type": "agent_skill"})
        self.assert_invalid(directory)

    def test_invalid_updated_at_is_rejected(self):
        for value in ("not-a-date", "2026-10-10"):
            with self.subTest(value=value):
                directory = self.make_skill(manifest_overrides={"updated_at": value})
                self.assert_invalid(directory)

    def test_skill_id_must_match_directory_name(self):
        directory = self.make_skill(skill_id="test-skill")
        (directory / "manifest.json").write_text(
            json.dumps(valid_manifest(skill_id="different-id"), ensure_ascii=False),
            encoding="utf-8",
        )
        self.assert_invalid(directory)

    def test_content_outside_the_skill_directory_is_rejected(self):
        outside = self.temp_path / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        directory = self.make_skill(manifest_overrides={"content": "../outside.md"})
        self.assert_invalid(directory)

    def test_missing_content_file_is_rejected(self):
        directory = self.make_skill(files={})
        self.assert_invalid(directory)

    def test_empty_content_file_is_rejected(self):
        directory = self.make_skill(files={"SKILL.md": "   \n"})
        self.assert_invalid(directory)

    def test_content_must_be_skill_md(self):
        directory = self.make_skill(
            manifest_overrides={"content": "notes.md"},
            files={"notes.md": "Arbitrary content reference."},
        )
        self.assert_invalid(directory)

    def test_executable_files_are_rejected(self):
        directory = self.make_skill(files={"run.bat": "@echo off\n"})
        self.assert_invalid(directory)

    def test_extra_files_are_rejected(self):
        for relative_path in ("extra.md", "extra/README.md"):
            with self.subTest(path=relative_path):
                directory = self.make_skill(files={**{"SKILL.md": "Use this."}, relative_path: "extra"})
                self.assert_invalid(directory)

    def test_stage_must_exist_in_every_selected_type_pack(self):
        supports = dict(valid_manifest()["supports"])
        supports["medium_ids"] = ["picturebook", "shortdrama"]
        supports["stage_ids"] = ["creation_delegate"]
        supports["artifact_ids"] = ["all"]
        directory = self.make_skill(manifest_overrides={"supports": supports})
        self.assert_invalid(directory)

    def test_artifact_must_exist_in_selected_type_pack(self):
        supports = dict(valid_manifest()["supports"])
        supports["medium_ids"] = ["picturebook"]
        supports["stage_ids"] = ["drafting"]
        supports["artifact_ids"] = ["episode_script"]
        directory = self.make_skill(manifest_overrides={"supports": supports})
        self.assert_invalid(directory)

    def test_all_medium_stage_and_artifact_are_accepted(self):
        supports = dict(valid_manifest()["supports"])
        supports.update(
            medium_ids=["all"], stage_ids=["all"], artifact_ids=["all"]
        )
        directory = self.make_skill(
            skill_id="all-skill", manifest_overrides={"supports": supports}
        )
        result = validate_user_skill(directory, ROOT)
        self.assertEqual(result.manifest["skill_id"], "all-skill")

    def test_noncanonical_medium_alias_is_rejected(self):
        supports = dict(valid_manifest()["supports"])
        supports.update(
            medium_ids=["picturebook-screenwriter"],
            stage_ids=["all"],
            artifact_ids=["all"],
        )
        directory = self.make_skill(manifest_overrides={"supports": supports})
        self.assert_invalid(directory)


class ValidateUserSkillTreeTests(UserSkillHubTestCase):
    def make_plugin_root(self):
        plugin_root = self.temp_path / "plugin-root"
        (plugin_root / "config").mkdir(parents=True)
        shutil.copy2(
            ROOT / "config" / "type-packs.json",
            plugin_root / "config" / "type-packs.json",
        )
        return plugin_root

    def test_duplicate_skill_ids_in_tree_are_rejected(self):
        plugin_root = self.make_plugin_root()
        user_skills = plugin_root / "skills" / "user-skills"
        user_skills.mkdir(parents=True)
        for name in ("first", "second"):
            directory = user_skills / name
            directory.mkdir()
            manifest = valid_manifest(skill_id="test-skill")
            (directory / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            (directory / "SKILL.md").write_text("Use this.", encoding="utf-8")
        with self.assertRaisesRegex(UserSkillHubError, "重复 skill_id"):
            validate_user_skill_tree(plugin_root)


if __name__ == "__main__":
    unittest.main()
