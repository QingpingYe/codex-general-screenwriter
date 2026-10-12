import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
for path in (
    str(ROOT / "scripts"),
    str(ROOT / "skills" / "user-skill-hub" / "scripts"),
):
    if path not in sys.path:
        sys.path.insert(0, path)

from user_skill_hub import (
    UserSkillHubError,
    install_user_skill_pack,
    validate_user_skill_tree,
)


HUB_SCRIPT = ROOT / "skills" / "user-skill-hub" / "scripts" / "user_skill_hub.py"


def valid_manifest(skill_id):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "title": "Install Skill",
        "description": "A staged install skill.",
        "user_name": "tester",
        "skill_type": "prompt_skill",
        "supports": {
            "medium_ids": ["shortdrama"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        },
        "content": "SKILL.md",
        "updated_at": "2026-10-10T00:00:00+08:00",
    }


class UserSkillInstallTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temp.name)
        self.addCleanup(self._temp.cleanup)

    def make_plugin_root(self):
        plugin_root = self.temp_path / "plugin-root"
        (plugin_root / "config").mkdir(parents=True)
        shutil.copy2(
            ROOT / "config" / "type-packs.json",
            plugin_root / "config" / "type-packs.json",
        )
        return plugin_root

    def make_staged(self, skill_id, content="# Staged\n## Input\nx\n",
                    omit_skill_md=False):
        staged = self.temp_path / "staging" / skill_id
        staged.mkdir(parents=True, exist_ok=True)
        (staged / "manifest.json").write_text(
            json.dumps(valid_manifest(skill_id), ensure_ascii=False),
            encoding="utf-8",
        )
        if not omit_skill_md:
            (staged / "SKILL.md").write_text(content, encoding="utf-8")
        return staged

    def staging_root(self, plugin_root):
        return plugin_root.parent / ".tmp" / "user-skill-hub"

    def target(self, plugin_root, skill_id):
        return plugin_root / "skills" / "user-skills" / skill_id

    def assert_staging_empty(self, plugin_root):
        staging_root = self.staging_root(plugin_root)
        leftovers = (
            [path.name for path in staging_root.iterdir()]
            if staging_root.exists() else []
        )
        self.assertEqual(leftovers, [])

    def test_install_new_pack_swaps_in_and_tree_validates(self):
        plugin_root = self.make_plugin_root()
        staged = self.make_staged("install-skill")

        skill = install_user_skill_pack(staged, plugin_root)

        target = self.target(plugin_root, "install-skill")
        self.assertEqual(skill.directory, target.resolve())
        self.assertTrue((target / "SKILL.md").is_file())
        validate_user_skill_tree(plugin_root)
        self.assert_staging_empty(plugin_root)

    def test_install_refuses_overwrite_without_flag(self):
        plugin_root = self.make_plugin_root()
        install_user_skill_pack(
            self.make_staged("keep-skill", content="# V1\n"), plugin_root
        )

        with self.assertRaises(UserSkillHubError):
            install_user_skill_pack(
                self.make_staged("keep-skill", content="# V2\n"), plugin_root
            )

        text = (self.target(plugin_root, "keep-skill") / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("# V1", text)

    def test_install_overwrite_replaces_content_and_cleans_backup(self):
        plugin_root = self.make_plugin_root()
        install_user_skill_pack(
            self.make_staged("swap-skill", content="# V1\n"), plugin_root
        )

        install_user_skill_pack(
            self.make_staged("swap-skill", content="# V2\n"),
            plugin_root,
            overwrite=True,
        )

        text = (self.target(plugin_root, "swap-skill") / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("# V2", text)
        self.assert_staging_empty(plugin_root)

    def test_install_rolls_back_when_post_swap_validation_fails(self):
        plugin_root = self.make_plugin_root()
        install_user_skill_pack(
            self.make_staged("roll-skill", content="# V1\n"), plugin_root
        )

        with mock.patch(
            "user_skill_hub.validate_user_skill_tree",
            side_effect=UserSkillHubError("boom"),
        ):
            with self.assertRaises(UserSkillHubError):
                install_user_skill_pack(
                    self.make_staged("roll-skill", content="# V2\n"),
                    plugin_root,
                    overwrite=True,
                )

        text = (self.target(plugin_root, "roll-skill") / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("# V1", text)

    def test_install_restores_pack_when_backup_rename_fails(self):
        plugin_root = self.make_plugin_root()
        install_user_skill_pack(
            self.make_staged("hold-skill", content="# V1\n"), plugin_root
        )
        target = self.target(plugin_root, "hold-skill")
        real_move = shutil.move

        def failing_move(source, destination):
            if str(source) == str(target):
                raise OSError("locked by another process")
            return real_move(source, destination)

        with mock.patch("user_skill_hub.shutil.move", side_effect=failing_move):
            with self.assertRaises(OSError):
                install_user_skill_pack(
                    self.make_staged("hold-skill", content="# V2\n"),
                    plugin_root,
                    overwrite=True,
                )

        self.assertTrue(target.is_dir())
        self.assertIn(
            "# V1", (target / "SKILL.md").read_text(encoding="utf-8")
        )

    def test_install_leaves_tree_untouched_when_staged_pack_invalid(self):
        plugin_root = self.make_plugin_root()
        staged = self.make_staged("bad-skill", omit_skill_md=True)

        with self.assertRaises(UserSkillHubError):
            install_user_skill_pack(staged, plugin_root)

        self.assertFalse(self.target(plugin_root, "bad-skill").exists())

    def test_cli_install_roundtrip(self):
        plugin_root = self.make_plugin_root()
        staged = self.make_staged("cli-skill")
        command = [
            sys.executable, str(HUB_SCRIPT), "install",
            "--staging", str(staged), "--plugin-root", str(plugin_root),
        ]

        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)

        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 1)
        self.assertIn("覆盖", second.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
