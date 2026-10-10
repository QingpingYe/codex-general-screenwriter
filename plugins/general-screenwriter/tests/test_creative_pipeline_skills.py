import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
STORY = ROOT / "skills" / "story-planning" / "SKILL.md"
PRE_CREATE = ROOT / "skills" / "pre_create-baseline" / "SKILL.md"
IN_CREATE = ROOT / "skills" / "in_create-baseline" / "SKILL.md"
POST_CREATE = ROOT / "skills" / "post_create-baseline" / "SKILL.md"
PRE_OUTPUT = ROOT / "skills" / "pre_output-baseline" / "SKILL.md"
QUALITY = ROOT / "skills" / "quality-baseline" / "SKILL.md"
ENTRY = ROOT / "skills" / "general-screenwriter" / "SKILL.md"
BASELINE_SKILLS = (
    "pre_create-baseline",
    "in_create-baseline",
    "post_create-baseline",
    "pre_output-baseline",
    "quality-baseline",
)
PICTUREBOOK_ONLY_DEPENDENCIES = ("text-craft", "craft-benchmark-check")


class StoryPlanningTests(unittest.TestCase):
    def test_explicit_lightweight_trigger_only(self):
        text = STORY.read_text(encoding="utf-8")
        self.assertIn("显式", text)
        self.assertIn("轻量", text)
        self.assertIn("不落盘", text)


class PreCreateBaselineTests(unittest.TestCase):
    def test_pre_create_reports_gaps_not_defaults(self):
        text = PRE_CREATE.read_text(encoding="utf-8")
        self.assertIn("缺口", text)
        self.assertIn("不猜默认值", text)


class InCreateBaselineTests(unittest.TestCase):
    def test_in_create_requires_structure_before_body(self):
        text = IN_CREATE.read_text(encoding="utf-8")
        self.assertIn("结构骨架", text)
        self.assertIn("边界卡", text)
        self.assertIn("text-craft", text)


class PostCreateBaselineTests(unittest.TestCase):
    def test_post_create_is_polish_not_rewrite(self):
        text = POST_CREATE.read_text(encoding="utf-8")
        self.assertIn("只做打磨", text)
        self.assertIn("不得新增", text)


class PreOutputBaselineTests(unittest.TestCase):
    def test_pre_output_uses_two_stage_review(self):
        text = PRE_OUTPUT.read_text(encoding="utf-8")
        self.assertIn("廉价代理", text)
        self.assertIn("语义判定", text)


class QualityBaselineTests(unittest.TestCase):
    def test_quality_baseline_complements_not_duplicates(self):
        text = QUALITY.read_text(encoding="utf-8")
        self.assertIn("不重复", text)
        self.assertIn("跨产物一致性", text)


class EntryWorkflowTests(unittest.TestCase):
    def test_entry_uses_all_five_slots(self):
        text = ENTRY.read_text(encoding="utf-8")
        for slot in ("pre_create", "in_create", "post_create", "pre_output", "quality"):
            with self.subTest(slot=slot):
                self.assertIn(f"{slot}-baseline", text)


class BaselineMediumScopeTests(unittest.TestCase):
    def metadata(self, skill_id):
        path = ROOT / "skills" / skill_id / "skill-meta.json"
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def text(self, skill_id):
        return (ROOT / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8")

    def test_all_baseline_skills_declare_all_mediums(self):
        for skill_id in BASELINE_SKILLS:
            with self.subTest(skill_id=skill_id):
                supports = self.metadata(skill_id)["supports"]
                self.assertEqual(supports["medium_ids"], ["all"])

    def test_baseline_documents_have_separate_medium_routing(self):
        for skill_id in BASELINE_SKILLS:
            with self.subTest(skill_id=skill_id):
                text = self.text(skill_id)
                self.assertIn("## Medium Routing", text)
                self.assertIn("### picturebook", text)
                self.assertIn("### shortdrama / tv_longform", text)

    def test_nonpicturebook_baseline_routing_excludes_picturebook_dependencies(self):
        for skill_id in BASELINE_SKILLS:
            with self.subTest(skill_id=skill_id):
                text = self.text(skill_id)
                for dependency in PICTUREBOOK_ONLY_DEPENDENCIES:
                    picturebook = text.split(
                        "### picturebook", 1
                    )[1].split("### shortdrama / tv_longform", 1)[0]
                    self.assertEqual(
                        text.count(dependency),
                        picturebook.count(dependency),
                        f"{skill_id} mentions {dependency} outside picturebook routing",
                    )


if __name__ == "__main__":
    unittest.main()
