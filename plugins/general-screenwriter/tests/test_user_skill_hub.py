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

from user_skill_hub import (
    SUPPORT_FIELDS,
    UserSkillHubError,
    validate_system_skill,
    validate_system_skill_tree,
    validate_user_skill,
    validate_user_skill_tree,
)


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


def system_metadata(skill_id, medium_id="all"):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "visibility": "system",
        "supports": {
            "medium_ids": [medium_id],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        },
    }


SYSTEM_METADATA_SCOPES = {
    "general-screenwriter": "all",
    "stage-orchestration": "all",
    "wiki-ingest": "all",
    "feishu-knowledge-store": "all",
    "knowledge-loader": "all",
    "lexile-check": "all",
    "story-planning": "all",
    "pre_create-baseline": "all",
    "in_create-baseline": "all",
    "post_create-baseline": "all",
    "pre_output-baseline": "all",
    "quality-baseline": "all",
    "session-export": "all",
    "user-skill-hub": "all",
    "text-craft": "picturebook",
    "craft-benchmark-check": "picturebook",
    "staging-planner": "picturebook",
    "image-prompt-architect": "picturebook",
    "image-generate": "picturebook",
    "illustration-export": "picturebook",
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


class SystemSkillMetadataTests(unittest.TestCase):
    def test_required_metadata_files_use_shared_scopes(self):
        for skill_id, medium_id in SYSTEM_METADATA_SCOPES.items():
            with self.subTest(skill_id=skill_id):
                path = ROOT / "skills" / skill_id / "skill-meta.json"
                self.assertTrue(path.is_file(), f"缺少 {path}")
                metadata = json.loads(path.read_text(encoding="utf-8-sig"))
                self.assertEqual(metadata, system_metadata(skill_id, medium_id))

    def test_installed_system_skills_validate_against_plugin_root(self):
        installed = [
            path
            for path in (ROOT / "skills").iterdir()
            if path.is_dir()
            and path.name != "user-skills"
            and (path / "SKILL.md").is_file()
        ]
        self.assertGreater(len(installed), 0)
        for directory in installed:
            with self.subTest(skill_id=directory.name):
                result = validate_system_skill(directory, ROOT)
                self.assertEqual(result.directory, directory.resolve())
                self.assertEqual(
                    result.metadata,
                    system_metadata(
                        directory.name, SYSTEM_METADATA_SCOPES[directory.name]
                    ),
                )


class ValidateSystemSkillTests(UserSkillHubTestCase):
    def setUp(self):
        super().setUp()
        self._system_skill_counter = 0

    def make_plugin_root(self):
        plugin_root = self.temp_path / "plugin-root"
        (plugin_root / "config").mkdir(parents=True)
        shutil.copy2(
            ROOT / "config" / "type-packs.json",
            plugin_root / "config" / "type-packs.json",
        )
        return plugin_root

    def make_system_skill(self, skill_id=None, metadata_overrides=None,
                          omit_metadata=False, include_skill_md=True):
        if skill_id is None:
            self._system_skill_counter += 1
            skill_id = f"system-skill-{self._system_skill_counter}"
        directory = self.temp_path / skill_id
        directory.mkdir(parents=True)
        metadata = system_metadata(skill_id)
        for key, value in (metadata_overrides or {}).items():
            if value is MISSING:
                metadata.pop(key, None)
            else:
                metadata[key] = value
        if not omit_metadata:
            (directory / "skill-meta.json").write_text(
                json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
            )
        if include_skill_md:
            (directory / "SKILL.md").write_text("Use this system skill.", encoding="utf-8")
        return directory

    def assert_invalid(self, directory):
        with self.assertRaises(UserSkillHubError):
            validate_system_skill(directory, ROOT)

    def test_accepts_valid_system_skill(self):
        directory = self.make_system_skill(skill_id="system-skill")
        result = validate_system_skill(directory, ROOT)
        self.assertEqual(result.directory, directory.resolve())
        self.assertEqual(result.metadata["skill_id"], "system-skill")

    def test_missing_fields_are_rejected(self):
        for field in ("schema_version", "skill_id", "visibility", "supports"):
            with self.subTest(field=field):
                directory = self.make_system_skill(
                    metadata_overrides={field: MISSING}
                )
                self.assert_invalid(directory)

    def test_unknown_fields_are_rejected(self):
        directory = self.make_system_skill(metadata_overrides={"title": "System"})
        self.assert_invalid(directory)

    def test_visibility_must_be_system(self):
        for value in ("user", "public", 1):
            with self.subTest(visibility=value):
                directory = self.make_system_skill(
                    metadata_overrides={"visibility": value}
                )
                self.assert_invalid(directory)

    def test_skill_id_must_match_directory_name(self):
        directory = self.make_system_skill(skill_id="system-skill")
        metadata = system_metadata("different-id")
        (directory / "skill-meta.json").write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        self.assert_invalid(directory)

    def test_support_fields_and_nonempty_arrays_are_required(self):
        for field in SUPPORT_FIELDS:
            with self.subTest(field=field):
                metadata = system_metadata("system-skill")
                metadata["supports"][field] = []
                directory = self.make_system_skill(
                    metadata_overrides={"supports": metadata["supports"]}
                )
                self.assert_invalid(directory)

    def test_unknown_support_fields_are_rejected(self):
        metadata = system_metadata("system-skill")
        metadata["supports"]["role_ids"] = ["all"]
        directory = self.make_system_skill(
            metadata_overrides={"supports": metadata["supports"]}
        )
        self.assert_invalid(directory)

    def test_concrete_stage_and_artifact_are_validated(self):
        metadata = system_metadata("system-skill")
        metadata["supports"]["medium_ids"] = ["picturebook"]
        metadata["supports"]["stage_ids"] = ["episode_design"]
        metadata["supports"]["artifact_ids"] = ["episode_outline"]
        directory = self.make_system_skill(
            metadata_overrides={"supports": metadata["supports"]}
        )
        self.assert_invalid(directory)

    def test_missing_skill_md_is_rejected(self):
        directory = self.make_system_skill(include_skill_md=False)
        self.assert_invalid(directory)

    def test_tree_validates_only_immediate_skill_directories(self):
        plugin_root = self.make_plugin_root()
        skills_root = plugin_root / "skills"
        valid = skills_root / "valid-skill"
        valid.mkdir(parents=True)
        (valid / "skill-meta.json").write_text(
            json.dumps(system_metadata("valid-skill"), ensure_ascii=False),
            encoding="utf-8",
        )
        (valid / "SKILL.md").write_text("Use this.", encoding="utf-8")
        ignored = skills_root / "not-a-skill"
        ignored.mkdir()
        (ignored / "skill-meta.json").write_text(
            json.dumps(system_metadata("ignored"), ensure_ascii=False),
            encoding="utf-8",
        )
        user_skills = skills_root / "user-skills"
        user_skills.mkdir()
        (user_skills / "SKILL.md").write_text("not system", encoding="utf-8")
        result = validate_system_skill_tree(plugin_root)
        self.assertEqual(
            [item.metadata["skill_id"] for item in result], ["valid-skill"]
        )

    def test_tree_rejects_installed_system_skill_without_metadata(self):
        plugin_root = self.make_plugin_root()
        directory = plugin_root / "skills" / "invalid-skill"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("Use this.", encoding="utf-8")
        with self.assertRaises(UserSkillHubError):
            validate_system_skill_tree(plugin_root)


if __name__ == "__main__":
    unittest.main()
