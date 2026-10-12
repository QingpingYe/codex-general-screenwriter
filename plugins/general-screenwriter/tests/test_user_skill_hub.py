import json
import hashlib
import os
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
    format_user_skills,
    load_matching_user_skills,
    preview_user_skill_warnings,
    SUPPORT_FIELDS,
    SKILL_TYPES,
    used_user_skill_record,
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

    def test_skill_id_must_use_canonical_format(self):
        invalid_ids = (
            "Test-Skill",
            "test_skill",
            "test skill",
            "-test-skill",
            "test-skill-",
            "",
        )
        for index, skill_id in enumerate(invalid_ids):
            with self.subTest(skill_id=skill_id):
                directory = self.make_skill(
                    skill_id=f"invalid-skill-{index}",
                    manifest_overrides={"skill_id": skill_id},
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

    def test_windows_junction_single_user_skill_pack_is_rejected(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-specific")
        import _winapi
        directory = self.make_skill(skill_id="real-skill")
        link = self.temp_path / "junction-skill"
        _winapi.CreateJunction(str(directory), str(link))
        with self.assertRaisesRegex(UserSkillHubError, "符号链接|junction"):
            validate_user_skill(link, ROOT)


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

    def _valid_skill_directory(self, plugin_root, skill_id):
        directory = plugin_root / "skills" / "user-skills" / skill_id
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(
            json.dumps(valid_manifest(skill_id=skill_id), ensure_ascii=False),
            encoding="utf-8",
        )
        (directory / "SKILL.md").write_text("Use this skill.", encoding="utf-8")
        return directory

    def test_symlinked_user_skill_directory_is_rejected(self):
        plugin_root = self.make_plugin_root()
        real_directory = self._valid_skill_directory(plugin_root, "real-skill")
        link = plugin_root / "skills" / "user-skills" / "skill-link"
        try:
            os.symlink(real_directory, link, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable on this platform: {error}")
        with self.assertRaisesRegex(UserSkillHubError, "符号链接"):
            validate_user_skill_tree(plugin_root)

    def test_windows_junction_user_skill_directory_is_rejected(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-specific")
        plugin_root = self.make_plugin_root()
        real_directory = self._valid_skill_directory(plugin_root, "real-skill")
        link = plugin_root / "skills" / "user-skills" / "skill-junction"
        import _winapi
        _winapi.CreateJunction(str(real_directory), str(link))
        with self.assertRaisesRegex(UserSkillHubError, "符号链接|junction"):
            validate_user_skill_tree(plugin_root)

    def test_pack_must_resolve_directly_under_user_skills(self):
        plugin_root = self.make_plugin_root()
        outside_root = self.temp_path / "outside-skills"
        outside_root.mkdir()
        outside = outside_root / "escaped-skill"
        outside.mkdir()
        (outside / "manifest.json").write_text(
            json.dumps(valid_manifest(skill_id="escaped-skill"), ensure_ascii=False),
            encoding="utf-8",
        )
        (outside / "SKILL.md").write_text("Use this skill.", encoding="utf-8")
        link = plugin_root / "skills" / "user-skills" / "escaped-skill"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable on this platform: {error}")
        with self.assertRaisesRegex(UserSkillHubError, "skills/user-skills|符号链接"):
            validate_user_skill_tree(plugin_root)

    def test_loose_files_in_user_skills_root_are_rejected(self):
        plugin_root = self.make_plugin_root()
        user_skills = plugin_root / "skills" / "user-skills"
        user_skills.mkdir(parents=True)
        (user_skills / "notes.md").write_text("loose file", encoding="utf-8")
        (user_skills / "tool.exe").write_bytes(b"MZ")
        with self.assertRaises(UserSkillHubError) as context:
            validate_user_skill_tree(plugin_root)
        self.assertTrue(
            any(name in str(context.exception) for name in ("notes.md", "tool.exe"))
        )


class MatchingAndInjectionTests(UserSkillHubTestCase):
    def make_plugin_root(self):
        plugin_root = self.temp_path / "plugin-root"
        (plugin_root / "config").mkdir(parents=True)
        shutil.copy2(
            ROOT / "config" / "type-packs.json",
            plugin_root / "config" / "type-packs.json",
        )
        return plugin_root

    def make_matching_skill(
        self, plugin_root, skill_id, supports_overrides=None, title="Shared Title"
    ):
        supports = {
            "medium_ids": ["all"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        }
        supports.update(supports_overrides or {})
        directory = plugin_root / "skills" / "user-skills" / skill_id
        directory.mkdir(parents=True)
        manifest = valid_manifest(skill_id=skill_id)
        manifest["title"] = title
        manifest["supports"] = supports
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "SKILL.md").write_text("Shared user skill.", encoding="utf-8")
        return directory

    def skill_ids(self, plugin_root, **context):
        return [
            skill.manifest["skill_id"]
            for skill in load_matching_user_skills(plugin_root, **context)
        ]

    def test_all_supports_match_every_valid_context(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(plugin_root, "all-skill")
        contexts = (
            {
                "medium_id": "shortdrama",
                "genre_ids": ["genre-a"],
                "series_id": "series-a",
                "project_id": "project-a",
                "stage_id": "episode_design",
                "artifact_id": "episode_outline",
            },
            {
                "medium_id": "picturebook",
                "genre_ids": [],
                "series_id": None,
                "project_id": None,
                "stage_id": None,
                "artifact_id": None,
            },
        )
        for context in contexts:
            with self.subTest(context=context):
                self.assertEqual(self.skill_ids(plugin_root, **context), ["all-skill"])

    def test_concrete_medium_only_matches_that_medium(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(
            plugin_root, "shortdrama-skill", {"medium_ids": ["shortdrama"]}
        )
        self.assertEqual(
            self.skill_ids(plugin_root, medium_id="shortdrama"),
            ["shortdrama-skill"],
        )
        self.assertEqual(
            self.skill_ids(plugin_root, medium_id="picturebook"), []
        )

    def test_concrete_series_and_project_require_matching_context(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(
            plugin_root,
            "scoped-skill",
            {"series_ids": ["series-a"], "project_ids": ["project-a"]},
        )
        self.make_matching_skill(plugin_root, "agnostic-skill")
        self.assertEqual(
            sorted(self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                series_id="series-a",
                project_id="project-a",
            )),
            ["agnostic-skill", "scoped-skill"],
        )
        self.assertEqual(
            self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                series_id="series-b",
                project_id="project-b",
            ),
            ["agnostic-skill"],
        )
        self.assertEqual(
            self.skill_ids(plugin_root, medium_id="shortdrama"),
            ["agnostic-skill"],
        )

    def test_stage_and_artifact_mismatches_reject_skill(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(
            plugin_root,
            "stage-artifact-skill",
            {
                "medium_ids": ["shortdrama"],
                "stage_ids": ["episode_design"],
                "artifact_ids": ["episode_outline"],
            },
        )
        self.assertEqual(
            self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                stage_id="episode_design",
                artifact_id="episode_outline",
            ),
            ["stage-artifact-skill"],
        )
        self.assertEqual(
            self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                stage_id="hook_design",
                artifact_id="episode_outline",
            ),
            [],
        )
        self.assertEqual(
            self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                stage_id="episode_design",
                artifact_id="episode_script",
            ),
            [],
        )
        self.assertEqual(
            self.skill_ids(plugin_root, medium_id="shortdrama"), []
        )

    def test_specificity_orders_by_context_dimension(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(plugin_root, "all-skill")
        self.make_matching_skill(
            plugin_root, "medium-skill", {"medium_ids": ["shortdrama"]}
        )
        self.make_matching_skill(
            plugin_root,
            "genre-skill",
            {"medium_ids": ["shortdrama"], "genre_ids": ["genre-a"]},
        )
        self.make_matching_skill(
            plugin_root,
            "series-skill",
            {
                "medium_ids": ["shortdrama"],
                "genre_ids": ["genre-a"],
                "series_ids": ["series-a"],
            },
        )
        self.make_matching_skill(
            plugin_root,
            "project-skill",
            {
                "medium_ids": ["shortdrama"],
                "genre_ids": ["genre-a"],
                "series_ids": ["series-a"],
                "project_ids": ["project-a"],
            },
        )
        self.assertEqual(
            self.skill_ids(
                plugin_root,
                medium_id="shortdrama",
                genre_ids=["genre-a"],
                series_id="series-a",
                project_id="project-a",
            ),
            [
                "project-skill",
                "series-skill",
                "genre-skill",
                "medium-skill",
                "all-skill",
            ],
        )

    def test_title_breaks_specificity_ties(self):
        plugin_root = self.make_plugin_root()
        self.make_matching_skill(
            plugin_root, "second-skill", title="B Skill"
        )
        self.make_matching_skill(
            plugin_root, "first-skill", title="A Skill"
        )
        self.assertEqual(
            self.skill_ids(plugin_root, medium_id="shortdrama"),
            ["first-skill", "second-skill"],
        )

    def test_format_user_skills_includes_all_injection_fields(self):
        directory = self.make_skill(skill_id="format-skill")
        skill = validate_user_skill(directory, ROOT)
        formatted = format_user_skills([skill])
        for value in (
            "Test Skill",
            "张三",
            "A valid test skill.",
            "Use this user skill.",
        ):
            with self.subTest(value=value):
                self.assertIn(value, formatted)

    def test_used_user_skill_record_contains_exact_fields(self):
        directory = self.make_skill(skill_id="record-skill")
        skill = validate_user_skill(directory, ROOT)
        content_hash = hashlib.sha256(
            (directory / "SKILL.md").read_bytes()
        ).hexdigest()
        record = used_user_skill_record(skill)
        self.assertEqual(
            record,
            {
                "skill_id": "record-skill",
                "title": "Test Skill",
                "user_name": "张三",
                "updated_at": "2026-10-10T00:00:00+08:00",
                "content_hash": f"sha256:{content_hash}",
            },
        )
        self.assertEqual(
            set(record),
            {"skill_id", "title", "user_name", "updated_at", "content_hash"},
        )

    def test_preview_warnings_cover_contract_risks(self):
        complete_content = (
            "# Skill\n\n## Input\nUse inputs.\n\n"
            "## Method\nDo the method.\n\n## Output\nOutput it.\n\n"
            "## Checkpoints\nCheck the work.\n"
        )

        broad_directory = self.make_skill(
            skill_id="broad-skill",
            manifest_overrides={
                "supports": {
                    "medium_ids": ["all"],
                    "genre_ids": ["all"],
                    "series_ids": ["all"],
                    "project_ids": ["all"],
                    "stage_ids": ["all"],
                    "artifact_ids": ["all"],
                }
            },
            files={"SKILL.md": complete_content},
        )
        broad = validate_user_skill(broad_directory, ROOT)
        broad_warnings = preview_user_skill_warnings(broad)
        self.assertTrue(any(item.startswith("all ") for item in broad_warnings))

        generic_directory = self.make_skill(
            skill_id="generic-skill",
            manifest_overrides={"title": "用户技能"},
            files={"SKILL.md": complete_content},
        )
        generic = validate_user_skill(generic_directory, ROOT)
        generic_warnings = preview_user_skill_warnings(generic)
        self.assertTrue(any(item.startswith("标题") for item in generic_warnings))

        incomplete_directory = self.make_skill(
            skill_id="incomplete-skill",
            files={"SKILL.md": "Use this."},
        )
        incomplete = validate_user_skill(incomplete_directory, ROOT)
        incomplete_warnings = preview_user_skill_warnings(incomplete)
        self.assertTrue(any(item.startswith("正文缺少") for item in incomplete_warnings))

        similar_directory = self.make_skill(
            skill_id="novel-adaptation",
            files={"SKILL.md": complete_content},
        )
        similar = validate_user_skill(similar_directory, ROOT)
        warnings = preview_user_skill_warnings(
            similar, existing_skill_ids=("novel-adaptations",)
        )
        self.assertIn("与已有 skill_id 相似", warnings[0])
        self.assertIn("novel-adaptation", warnings[0])
        self.assertIn("novel-adaptations", warnings[0])


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
        user_skills = skills_root / "user-skills"
        user_skills.mkdir()
        (user_skills / "SKILL.md").write_text("not system", encoding="utf-8")
        result = validate_system_skill_tree(plugin_root)
        self.assertEqual(
            [item.metadata["skill_id"] for item in result], ["valid-skill"]
        )

    def test_windows_junction_system_skill_is_rejected(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-specific")
        import _winapi
        directory = self.make_system_skill(skill_id="real-system")
        link = self.temp_path / "junction-system"
        _winapi.CreateJunction(str(directory), str(link))
        with self.assertRaisesRegex(UserSkillHubError, "符号链接|junction"):
            validate_system_skill(link, ROOT)

    def test_tree_rejects_half_installed_system_skill(self):
        plugin_root = self.make_plugin_root()
        directory = plugin_root / "skills" / "half-installed"
        directory.mkdir(parents=True)
        (directory / "skill-meta.json").write_text(
            json.dumps(system_metadata("half-installed"), ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaises(UserSkillHubError):
            validate_system_skill_tree(plugin_root)

    def test_tree_rejects_installed_system_skill_without_metadata(self):
        plugin_root = self.make_plugin_root()
        directory = plugin_root / "skills" / "invalid-skill"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("Use this.", encoding="utf-8")
        with self.assertRaises(UserSkillHubError):
            validate_system_skill_tree(plugin_root)


class HubSkillAndSampleTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(
            (ROOT / "config" / "plugin-contract.json").read_text(encoding="utf-8")
        )
        self.hub_skill = (
            ROOT / "skills" / "user-skill-hub" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_real_user_skill_tree_validates(self):
        skills = validate_user_skill_tree(ROOT)
        self.assertEqual(
            [skill.manifest["skill_id"] for skill in skills],
            ["novel-to-shortdrama-adaptation"],
        )

    def test_sample_manifest_declares_owner_and_complete_supports(self):
        path = (
            ROOT / "skills" / "user-skills" /
            "novel-to-shortdrama-adaptation" / "manifest.json"
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["user_name"], "QingpingYe")
        self.assertEqual(manifest["skill_type"], "prompt_skill")
        self.assertEqual(
            manifest["supports"],
            {
                "medium_ids": ["shortdrama"],
                "genre_ids": ["all"],
                "series_ids": ["all"],
                "project_ids": ["all"],
                "stage_ids": [
                    "brief_gate",
                    "knowledge_load",
                    "episode_design",
                    "hook_design",
                    "beat_design",
                    "scene_design",
                    "episode_script_delegate",
                    "hook_check",
                    "pacing_check",
                    "dialogue_check",
                    "quality_gate",
                ],
                "artifact_ids": [
                    "episode_outline",
                    "hook_sheet",
                    "beat_sheet",
                    "scene_table",
                    "episode_script",
                ],
            },
        )
        for field in SUPPORT_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(manifest["supports"][field])

    def test_hub_requires_user_name_before_create_or_import(self):
        self.assertIn("创建或导入用户技能前，必须先询问 user_name", self.hub_skill)

    def test_hub_requires_overwrite_confirmation(self):
        self.assertIn("覆盖现有技能前必须获得用户明确确认", self.hub_skill)

    def test_hub_does_not_expose_internal_commands_as_interface(self):
        self.assertIn("不得把内部命令作为用户界面", self.hub_skill)

    def test_hub_keeps_skills_local_only(self):
        self.assertIn("只保存在本地插件目录", self.hub_skill)
        self.assertIn("不提交", self.hub_skill)
        self.assertIn("不推送", self.hub_skill)
        self.assertIn("不改插件版本号", self.hub_skill)
        self.assertNotIn("机械递增", self.hub_skill)

    def test_hub_has_no_git_workflow(self):
        for phrase in ("git push", "force push", "pull/rebase", "暂存目标技能目录"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.hub_skill)

    def test_hub_regenerates_local_index_after_install(self):
        self.assertIn("重新生成 `config/skill-index.json`", self.hub_skill)

    def test_contract_declares_user_skill_hub(self):
        self.assertIn("user-skill-hub", self.contract["skills"])
        self.assertEqual(
            self.contract["user_skill_hub"],
            {
                "schema_version": "user-skill-hub-v2",
                "wildcard_value": "all",
                "required_user_field": "user_name",
                "skill_types": [
                    "prompt_skill",
                    "checklist_skill",
                    "reference_skill",
                    "exporter_skill",
                ],
                "allow_executable_files": False,
            },
        )

    def test_contract_matches_validator_policy(self):
        hub_contract = self.contract["user_skill_hub"]
        self.assertEqual(hub_contract["wildcard_value"], "all")
        self.assertEqual(hub_contract["required_user_field"], "user_name")
        self.assertEqual(set(hub_contract["skill_types"]), SKILL_TYPES)
        self.assertFalse(hub_contract["allow_executable_files"])

    def test_readme_documents_user_skill_hub_contract(self):
        readme = (ROOT.parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("user-skill-hub", self.contract["skills"])
        self.assertIn("自然对话", readme)
        self.assertIn("user_name", readme)
        self.assertIn("覆盖", readme)
        self.assertIn("不会为它执行 git 提交或推送", readme)
        self.assertIn("系统技能", readme)
        for phrase in (
            "all",
            "非空",
            "不能留空数组",
            "不能携带可执行文件",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)

    def test_hub_describes_local_storage_without_publishing(self):
        self.assertIn(
            "只保存在本地插件目录 `skills/user-skills/<skill_id>/`",
            self.hub_skill,
        )
        self.assertNotIn("Marketplace", self.hub_skill)


if __name__ == "__main__":
    unittest.main()
