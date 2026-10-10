import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
STORE_SCRIPTS = str(ROOT / "skills" / "feishu-knowledge-store" / "scripts")
LOADER_SCRIPTS = str(ROOT / "skills" / "knowledge-loader" / "scripts")
if STORE_SCRIPTS not in sys.path:
    sys.path.insert(0, STORE_SCRIPTS)
if LOADER_SCRIPTS not in sys.path:
    sys.path.insert(0, LOADER_SCRIPTS)

import stage_dag
import stage_dag_codex
import type_registry as tr
from creative_run_builder import CreativeRunRequest, build_creative_run
from screenwriter_context import CreativeContext


CONTRACT = ROOT / "config" / "plugin-contract.json"


class PicturebookMigrationMatrixTests(unittest.TestCase):
    @staticmethod
    def _fast_forward(manifest, stage_ids):
        for stage_id in stage_ids:
            for status in ("ready", "running", "done"):
                manifest = stage_dag.transition_stage(manifest, stage_id, status)
        return manifest

    @staticmethod
    def _complete_confirmation(manifest, outcome):
        for status in ("ready", "running"):
            manifest = stage_dag.transition_stage(manifest, "confirmation_gate", status)
        return stage_dag.transition_stage(manifest, "confirmation_gate", "done", outcome=outcome)

    def test_contract_declares_picturebook_migration(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        migration = contract["picturebook_migration"]
        self.assertEqual(migration["text_core_status"], "migrated")
        self.assertEqual(migration["illustration_workflow_status"], "migrated")
        self.assertEqual(migration["knowledge_adapter_status"], "v1_compatible")
        self.assertEqual(
            set(migration["legacy_aliases"]),
            {
                "picturebook-screenwriter", "pb-stage-run-v2", "pb-stage-task-v1",
                "pb-screenwriter", "illustration-template",
            },
        )

    def test_legacy_no_context_run_remains_picturebook(self):
        manifest = stage_dag._creation_template_manifest()
        self.assertEqual(stage_dag.extract_context(manifest).medium_id, "picturebook")
        self.assertNotIn("context", manifest)

    def test_legacy_illustration_run_is_readable(self):
        manifest = stage_dag._illustration_template_manifest()
        self.assertEqual(stage_dag.validate_manifest(manifest), manifest)

    def test_new_picturebook_creation_parses_core_artifacts(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picturebook")
        manifest = build_creative_run(CreativeRunRequest(
            type_pack=pack,
            context=CreativeContext("picturebook", project_id="p1",
                                    delivery_form="page_script"),
            intent="creation", target="script", run_id="matrix-run-1",
            project_root=str(REPO_ROOT),
        ))
        self.assertEqual(manifest["artifact_type"], "script")
        self.assertEqual(manifest["resolution_snapshot"]["artifact"]["artifact_id"], "script")
        self.assertEqual(stage_dag.ready_stages(manifest), ["session_init"])

    def test_new_picturebook_revision_inherits_isolated_snapshot(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["project_root"] = str(REPO_ROOT)
        manifest = stage_dag.attach_context(
            manifest,
            CreativeContext("picturebook", project_id="p1"),
            {"type_pack": {"medium_id": "picturebook", "version": "picturebook-v1"}},
        )
        manifest = self._fast_forward(manifest, [
            "session_init", "brief_gate", "knowledge_load", "creation_delegate",
            "preflight", "collision_check", "qa", "qa_synthesis",
        ])
        manifest = self._complete_confirmation(manifest, "revision_requested")
        parent = stage_dag.finalize_run(manifest, "revision_requested")

        revision = stage_dag.build_revision_manifest(
            parent,
            feedback=[{"issue": "hook", "instruction": "strengthen"}],
            artifact_ref="plugins/picturebook-screenwriter/config/type-packs.json",
            run_id="matrix-revision-0002",
        )
        self.assertEqual(revision["revision_of_run_id"], parent["run_id"])
        self.assertEqual(
            {key: revision["resolution_snapshot"]["type_pack"][key]
             for key in parent["resolution_snapshot"]["type_pack"]},
            parent["resolution_snapshot"]["type_pack"],
        )
        self.assertEqual(
            [rule["check_id"] for rule in revision["resolution_snapshot"]["quality_rules"]],
            ["project_authority", "knowledge_collision", "craft_benchmark"],
        )

    def test_planned_media_are_not_dispatched(self):
        for medium, version in (("shortdrama", "shortdrama-v1"),
                                ("tv_longform", "tv_longform-v1")):
            with self.subTest(medium=medium):
                manifest = stage_dag.attach_context(
                    stage_dag._creation_template_manifest(),
                    CreativeContext(medium, project_id="p1"),
                    {"type_pack": {"medium_id": medium, "version": version}},
                )
                self.assertEqual(stage_dag.validate_manifest(manifest), manifest)
                with self.assertRaises(tr.TypePackNotExecutableError):
                    stage_dag_codex.build_dispatch_plan(manifest)

    def test_empty_active_picturebook_pack_is_rejected(self):
        payload = json.loads(
            (ROOT / "config" / "type-packs.json").read_text(encoding="utf-8"))
        payload["packs"][0]["artifact_types"] = []
        payload["packs"][0]["stages"] = []
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(payload)

    def test_illustration_mixed_into_core_is_rejected(self):
        payload = json.loads(
            (ROOT / "config" / "type-packs.json").read_text(encoding="utf-8"))
        core = payload["packs"][0]
        illustration = next(
            workflow for workflow in core["optional_workflows"]
            if workflow["workflow_id"] == "illustration"
        )
        core["stages"].append(copy.deepcopy(illustration["stages"][0]))
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(payload)

    def test_illustration_without_script_provenance_is_not_dispatched(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picturebook")
        workflow = tr.resolve_workflow(pack, "illustration")
        html = tr.resolve_workflow_artifact(workflow, "html_preview")
        snapshot = stage_dag.build_resolution_snapshot(pack, html, workflow)
        manifest = stage_dag.attach_context(
            stage_dag._illustration_template_manifest(),
            CreativeContext("picturebook", project_id="p1"),
            snapshot,
        )
        manifest["artifact_type"] = "illustration"
        manifest = stage_dag.validate_manifest(manifest)
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag_codex.build_dispatch_plan(manifest)

    def test_v1_knowledge_key_remains_readable(self):
        from page_codec import parse_remote_page, render_remote_page
        from scope_pages import parse_scope_envelope
        from shared_schema import logical_key

        self.assertEqual(logical_key("s1", "p1", "worldview"), "s1/p1/worldview")
        page = parse_remote_page(render_remote_page(
            "# 世界观\n\n正文。\n",
            {"key": "s1/p1/worldview", "page_type": "worldview",
             "source_node_tokens": ["src1"], "source_revisions": {"src1": "r1"},
             "last_ai_revision_id": 1},
        ))
        self.assertIsNone(parse_scope_envelope(page.body))


if __name__ == "__main__":
    unittest.main(verbosity=2)
