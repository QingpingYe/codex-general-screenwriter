import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
import stage_dag_codex
from screenwriter_context import CreativeContext
from type_registry import load_type_registry, resolve_type_pack, TypePackNotExecutableError


class ScreenwriterFoundationIntegrationTests(unittest.TestCase):
    @staticmethod
    def _fast_forward(manifest, stage_ids):
        for stage_id in stage_ids:
            for status in ("ready", "running", "done"):
                manifest = stage_dag.transition_stage(manifest, stage_id, status)
        return manifest

    @staticmethod
    def _complete_confirmation(manifest, outcome):
        for status in ("ready", "running"):
            manifest = stage_dag.transition_stage(
                manifest, "confirmation_gate", status
            )
        return stage_dag.transition_stage(
            manifest, "confirmation_gate", "done", outcome=outcome
        )

    def test_text_only_core_completes_without_optional_illustration_work(self):
        pack = resolve_type_pack(load_type_registry(), "picturebook")
        self.assertEqual(len(pack.optional_workflows), 1)
        workflow = pack.optional_workflows[0]
        self.assertFalse(workflow.required)
        self.assertFalse(workflow.blocks_core_completion)
        manifest = stage_dag._creation_template_manifest()
        optional_ids = {stage.stage_id for stage in workflow.stages}
        self.assertTrue(optional_ids.isdisjoint(stage["stage_id"] for stage in manifest["stages"]))
        manifest = self._fast_forward(manifest, [
            "session_init", "brief_gate", "knowledge_load", "creation_delegate",
            "preflight", "collision_check", "qa", "qa_synthesis",
        ])
        manifest = self._complete_confirmation(manifest, "approved")
        manifest = self._fast_forward(manifest, ["persistence", "knowledge_reminder"])
        completed = stage_dag.finalize_run(manifest, "approved")
        self.assertEqual((completed["status"], completed["outcome"]), ("completed", "approved"))

    def test_registry_context_dispatch_and_revision_compatibility(self):
        registry = load_type_registry(ROOT / "config" / "type-packs.json")
        film = resolve_type_pack(registry, "film")
        self.assertEqual(film.medium_id, "film")
        self.assertEqual(film.status, "planned")

        manifest = stage_dag._creation_template_manifest()
        manifest["project_root"] = str(REPO_ROOT)
        manifest = stage_dag.attach_context(
            manifest,
            CreativeContext("film", ("mystery",), project_id="film-one"),
            {"type_pack": {"medium_id": "film", "version": "0.1.0"}},
        )
        stage_dag.validate_manifest(manifest)
        with self.assertRaises(TypePackNotExecutableError):
            stage_dag_codex.build_dispatch_plan(manifest)
        with self.assertRaises(TypePackNotExecutableError):
            stage_dag_codex.build_sequential_fallback(manifest)
        with self.assertRaises(TypePackNotExecutableError):
            stage_dag_codex.format_task_envelope(manifest, manifest["stages"][1])

        # The old planned-medium manifest remains readable, but cannot advance.
        # Exercise revision lineage with a current, executable picturebook run.
        manifest = stage_dag.attach_context(
            stage_dag._creation_template_manifest(),
            CreativeContext("picturebook", project_id="picturebook-one"),
            {"type_pack": {"medium_id": "picturebook", "version": "picturebook-v1"}},
        )
        manifest["project_root"] = str(REPO_ROOT)
        parent = self._fast_forward(manifest, [
            "session_init", "brief_gate", "knowledge_load", "creation_delegate",
            "preflight", "collision_check", "qa", "qa_synthesis",
        ])
        parent = self._complete_confirmation(parent, "revision_requested")
        parent = stage_dag.finalize_run(parent, "revision_requested")
        revision = stage_dag.build_revision_manifest(
            parent,
            feedback=[{"issue": "hook", "instruction": "strengthen"}],
            artifact_ref="plugins/picturebook-screenwriter/config/type-packs.json",
            run_id="foundation-integration-revision-0002",
        )
        self.assertEqual(revision["context"], parent["context"])
        self.assertEqual(revision["revision_of_run_id"], parent["run_id"])

        legacy = stage_dag._creation_template_manifest()
        self.assertEqual(stage_dag.extract_context(legacy).medium_id, "picturebook")


if __name__ == "__main__":
    unittest.main(verbosity=2)
