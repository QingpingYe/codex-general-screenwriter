import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import package_check
import release_gate
import run_plugin_tests


RELEASE_DOC = REPO_ROOT / "docs" / "RELEASE.md"
CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
REPO_README = REPO_ROOT / "README.md"
PLUGIN_README = PLUGIN_ROOT / "README.md"
MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"

LIVE_GATE_MARKERS = (
    ("clean Windows VM", "干净 Windows VM"),
    ("existing higher-version CLI", "已有更高版本 CLI"),
    ("two real users", "两个真实用户"),
    ("no global install", "无全局安装"),
    ("no credential leakage", "无凭证泄漏"),
    ("interrupted recovery", "中断恢复"),
)

REQUIRED_FIRST_USE_TEST_PATHS = {
    Path("tests") / "test_first_use_release_contract.py",
    Path("tests") / "test_first_use_e2e.py",
    Path("tests") / "test_setup_contract.py",
}


def _markdown_section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


class FirstUseReleaseGateTests(unittest.TestCase):
    def test_first_use_steps_run_before_offline_regression(self):
        names = [name for name, _ in release_gate.GATE_STEPS]
        steps = dict(release_gate.GATE_STEPS)

        self.assertIn("first_use_contract", names)
        self.assertIn("setup_docs_contract", names)
        self.assertLess(names.index("first_use_contract"), names.index("offline_regression"))
        self.assertLess(names.index("setup_docs_contract"), names.index("offline_regression"))
        self.assertIn(
            "test_first_use_release_contract.py", steps["first_use_contract"]
        )
        self.assertIn("test_setup_contract.py", steps["setup_docs_contract"])

    def test_aggregate_runner_declares_and_discovers_first_use_suites(self):
        self.assertEqual(
            set(run_plugin_tests.REQUIRED_FIRST_USE_TEST_PATHS),
            REQUIRED_FIRST_USE_TEST_PATHS,
        )
        discovered = set(
            run_plugin_tests.discover_python_tests((PLUGIN_ROOT, SCRIPTS))
        )
        required = {
            PLUGIN_ROOT / relative for relative in REQUIRED_FIRST_USE_TEST_PATHS
        }
        self.assertTrue(required.issubset(discovered))


class FirstUseReleaseDocsTests(unittest.TestCase):
    def test_release_docs_cover_the_six_live_acceptance_classes(self):
        text = RELEASE_DOC.read_text(encoding="utf-8")
        for english, chinese in LIVE_GATE_MARKERS:
            with self.subTest(gate=english):
                self.assertIn(english, text)
                self.assertIn(chinese, text)

    def test_live_gates_are_explicitly_unexecuted_and_manual(self):
        text = RELEASE_DOC.read_text(encoding="utf-8").lower()
        self.assertIn("requires execution", text)
        self.assertIn("not run", text)
        self.assertIn("offline tests are not live acceptance evidence", text)

    def test_first_use_user_docs_stay_natural_language(self):
        repo_text = REPO_README.read_text(encoding="utf-8")
        setup = _markdown_section(repo_text, "## Feishu knowledge setup")
        self.assertIn("帮我初始化编剧插件", setup)
        self.assertIn("不需要用户执行飞书命令", setup)
        for forbidden in (
            "lark-cli",
            "store_cli.py",
            "authority_cli.py",
            "config init",
            "npm install",
            "python .\\",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, setup)

        plugin_text = PLUGIN_README.read_text(encoding="utf-8")
        self.assertIn("正常流程不需要用户执行飞书命令", plugin_text)
        self.assertNotIn("```", plugin_text)

    def test_release_version_and_first_use_surface_are_synchronized(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        changelog = CHANGELOG.read_text(encoding="utf-8")

        self.assertEqual(manifest["version"], "0.9.0")
        self.assertIn("first-use", manifest["description"].lower())
        self.assertIn("## [0.9.0]", changelog)
        self.assertIn("first-use", changelog.lower())
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "general-screenwriter")
        self.assertEqual(entry["policy"]["authentication"], "ON_USE")


class FirstUseCredentialPackageTests(unittest.TestCase):
    def test_package_check_rejects_persisted_device_and_user_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plugin = root / "plugins" / "general-screenwriter"
            (plugin / ".codex-plugin").mkdir(parents=True)
            (plugin / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"version": "1.2.3"}), encoding="utf-8"
            )
            (plugin / "config").mkdir()
            (plugin / "config" / "state.json").write_text(
                json.dumps({
                    "authorization": {
                        "device_code": "live-device-code",
                        "user_code": "LIVE-CODE",
                    }
                }),
                encoding="utf-8",
            )

            report = package_check.build_package_report(root)
            errors = "\n".join(report.errors)
            self.assertIn("device_code", errors)
            self.assertIn("user_code", errors)


if __name__ == "__main__":
    unittest.main()
