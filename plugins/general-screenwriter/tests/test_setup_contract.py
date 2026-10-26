import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONTRACT = ROOT / "config" / "plugin-contract.json"
INDEX = ROOT / "config" / "skill-index.json"
MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
SETUP_SKILL = ROOT / "skills" / "setup" / "SKILL.md"
ENTRY_SKILLS = (
    ROOT / "skills" / "general-screenwriter" / "SKILL.md",
    ROOT / "skills" / "feishu-knowledge-store" / "SKILL.md",
    ROOT / "skills" / "wiki-ingest" / "SKILL.md",
    ROOT / "skills" / "knowledge-loader" / "SKILL.md",
)
USER_DOCS = (
    ROOT.parent.parent / "README.md",
    ROOT / "README.md",
    ROOT / "skills" / "wiki-ingest" / "references" / "feishu-wiki-extraction.md",
)

FORBIDDEN_USER_COMMANDS = (
    r"lark-cli\s+auth\s+login",
    r"\bconfig\s+init\b",
    r"\bnpx\b[^\n`]*\binstall\b",
)
FORBIDDEN_USER_INSTRUCTIONS = (
    r"复制[^\n]{0,20}(配置|模板)",
    r"copy[^\n]{0,30}(config|template)",
    r"重开(?:终端|命令行)",
    r"重启(?:终端|命令行)",
    r"restart[^\n]{0,20}terminal",
)


class SetupContractTests(unittest.TestCase):
    def test_setup_skill_is_registered_and_indexed(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        self.assertIn("setup", contract["skills"])
        entries = {entry["skill_id"]: entry for entry in index["entries"]}
        self.assertIn("setup", entries)
        self.assertEqual(entries["setup"]["layer"], "system")
        self.assertEqual(entries["setup"]["supports"], {
            "medium_ids": ["all"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["all"],
            "artifact_ids": ["all"],
        })
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertTrue(SETUP_SKILL.is_file())
        self.assertIn("初始", manifest["interface"]["longDescription"])
        self.assertIn("帮我初始化编剧插件", manifest["interface"]["defaultPrompt"])

    def test_all_feishu_entry_skills_require_setup_and_resume_original_task(self):
        for path in ENTRY_SKILLS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("setup", text)
                self.assertIn("先检查 setup", text)
                self.assertIn("恢复原任务", text)
                self.assertIn("ready", text)

    def test_wiki_ingest_does_not_bypass_setup_for_install_or_login(self):
        paths = (
            ROOT / "skills" / "wiki-ingest" / "SKILL.md",
            ROOT / "skills" / "wiki-ingest" / "references" / "feishu-wiki-extraction.md",
        )
        bypass_patterns = (
            r"经用户批准.{0,12}(安装|安装器)",
            r"用户批准.{0,12}安装",
            r"提示用户.{0,12}重新登录",
            r"用户.{0,12}重新登录",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("setup", text)
                self.assertIn("ready", text)
                for pattern in bypass_patterns:
                    self.assertIsNone(re.search(pattern, text, re.IGNORECASE))
    def test_setup_skill_is_ai_internal_and_has_no_user_facing_commands(self):
        text = SETUP_SKILL.read_text(encoding="utf-8")
        self.assertIn("内部", text)
        self.assertIn("自然语言", text)
        self.assertIn("恢复原任务", text)
        self.assertIn("ready", text)
        self.assertNotIn("```", text)

    def test_user_docs_do_not_require_manual_setup_commands_or_restarts(self):
        for path in USER_DOCS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for pattern in (*FORBIDDEN_USER_COMMANDS, *FORBIDDEN_USER_INSTRUCTIONS):
                    with self.subTest(pattern=pattern):
                        self.assertIsNone(re.search(pattern, text, re.IGNORECASE))

    def test_setup_cli_exposes_only_the_internal_json_commands(self):
        sys.path.insert(0, str(ROOT / "skills" / "setup" / "scripts"))
        import setup_cli

        self.assertEqual(set(setup_cli.COMMANDS), {
            "doctor",
            "auth-start",
            "auth-complete",
            "config-from-links",
            "target-init",
            "write-verify",
        })


if __name__ == "__main__":
    unittest.main()
