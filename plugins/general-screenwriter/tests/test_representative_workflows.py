import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sample_workflow import (
    SampleWorkflowError,
    load_sample,
    run_sample_workflow,
)


FIXTURES = ROOT / "tests" / "fixtures"
SHORTDRAMA_PASS = FIXTURES / "shortdrama-pass.json"
SHORTDRAMA_FAIL = FIXTURES / "shortdrama-fail.json"
TV_PASS = FIXTURES / "tv-longform-pass.json"
TV_FAIL = FIXTURES / "tv-longform-fail.json"
PICTUREBOOK_PASS = FIXTURES / "picturebook-pass.json"
PICTUREBOOK_FAIL = FIXTURES / "picturebook-fail.json"


class RepresentativeWorkflowTests(unittest.TestCase):
    def test_shortdrama_samples_execute_real_validators(self):
        result = run_sample_workflow(load_sample(SHORTDRAMA_PASS))
        self.assertEqual(result.execution, "deterministic")
        self.assertTrue(result.confirmation_ready)
        self.assertTrue(result.report.passed)
        for item in result.report.checks:
            self.assertEqual(item.evidence["execution"], "validator")
            self.assertEqual(item.evidence["source"], "content")

    def test_shortdrama_fail_sample_is_blocked_by_real_content(self):
        result = run_sample_workflow(load_sample(SHORTDRAMA_FAIL))
        self.assertFalse(result.confirmation_ready)
        self.assertTrue(result.report.passed)
        self.assertEqual(
            [item.check_id for item in result.report.requires_user_confirmation],
            ["closing_hook"],
        )
        self.assertIsNotNone(result.failure_reason)

    def test_longform_pass_sample_confirms(self):
        result = run_sample_workflow(load_sample(TV_PASS))
        self.assertTrue(result.confirmation_ready)
        self.assertEqual([item.check_id for item in result.report.blockers], [])

    def test_longform_fail_sample_blocks_exactly_character_state(self):
        result = run_sample_workflow(load_sample(TV_FAIL))
        self.assertFalse(result.confirmation_ready)
        self.assertFalse(result.report.passed)
        self.assertEqual(
            [item.check_id for item in result.report.blockers],
            ["character_state"],
        )

    def test_pipeline_stage_chain_must_be_topologically_valid(self):
        sample = load_sample(SHORTDRAMA_PASS)
        broken = replace(
            sample, pipeline_stages=tuple(reversed(sample.pipeline_stages)),
        )
        with self.assertRaises(SampleWorkflowError):
            run_sample_workflow(broken)

    def test_pipeline_chain_must_end_with_confirmation_gate(self):
        sample = load_sample(SHORTDRAMA_PASS)
        broken = replace(sample, pipeline_stages=sample.pipeline_stages[:-1])
        with self.assertRaises(SampleWorkflowError):
            run_sample_workflow(broken)

    def test_sample_rules_must_match_pack(self):
        sample = load_sample(SHORTDRAMA_PASS)
        tampered = [dict(rule) for rule in sample.quality_rules]
        tampered[0]["blocking_policy"] = "advisory"
        broken = replace(sample, quality_rules=tuple(tampered))
        with self.assertRaises(SampleWorkflowError):
            run_sample_workflow(broken)

    def test_export_preview_renders_without_writing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                shortdrama = run_sample_workflow(load_sample(SHORTDRAMA_PASS))
                longform = run_sample_workflow(load_sample(TV_PASS))
            finally:
                os.chdir(previous)
            self.assertEqual(os.listdir(tmp), [])
        self.assertIn("shortdrama_episode_script", shortdrama.export_previews)
        self.assertIn(
            "场1 天台 夜",
            shortdrama.export_previews["shortdrama_episode_script"],
        )
        self.assertIn("tv_season_package", longform.export_previews)
        self.assertIn(
            "季弧线目标：", longform.export_previews["tv_season_package"],
        )

    def test_declarative_samples_keep_skill_layer_evaluation(self):
        passing = run_sample_workflow(load_sample(PICTUREBOOK_PASS))
        failing = run_sample_workflow(load_sample(PICTUREBOOK_FAIL))
        self.assertEqual(passing.execution, "declarative")
        self.assertTrue(passing.confirmation_ready)
        self.assertFalse(failing.confirmation_ready)
        for item in failing.report.checks:
            self.assertEqual(item.evidence["execution"], "fixture")
        self.assertEqual(
            [item.check_id for item in failing.report.requires_user_confirmation],
            ["craft_benchmark"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
