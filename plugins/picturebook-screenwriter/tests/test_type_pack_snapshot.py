import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_dag as dag
import stage_dag_codex as codex
from screenwriter_context import CreativeContext
from type_registry import load_type_registry, resolve_type_pack, resolve_artifact, resolve_workflow, resolve_workflow_artifact


def advance(manifest, ids):
    for sid in ids:
        for state in ("ready", "running", "done"):
            manifest = dag.transition_stage(manifest, sid, state)
    return manifest


def revision_parent(manifest):
    manifest = advance(manifest, ["session_init", "brief_gate", "knowledge_load", "creation_delegate",
                                  "preflight", "collision_check", "qa", "qa_synthesis"])
    for state in ("ready", "running"):
        manifest = dag.transition_stage(manifest, "confirmation_gate", state)
    manifest = dag.transition_stage(manifest, "confirmation_gate", "done", outcome="revision_requested")
    return dag.finalize_run(manifest, "revision_requested")


class TypePackSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.pack = resolve_type_pack(load_type_registry(), "picturebook")
        self.script = resolve_artifact(self.pack, "script")
        self.workflow = resolve_workflow(self.pack, "illustration")

    def manifest(self, snapshot=None):
        manifest = dag._creation_template_manifest()
        manifest["project_root"] = str(REPO_ROOT)
        return dag.attach_context(manifest, CreativeContext("picturebook", project_id="p1"),
                                  snapshot or dag.build_resolution_snapshot(self.pack, self.script))

    def test_builds_precise_core_and_optional_workflow_snapshot(self):
        snapshot = dag.build_resolution_snapshot(self.pack, self.script)
        self.assertEqual(snapshot, dict(type_pack=dict(medium_id="picturebook", version="picturebook-v1",
                                                       workflow_policy="picturebook-v1"),
                                         artifact=dict(artifact_id="script", delivery_form="page_script")))
        html = resolve_workflow_artifact(self.workflow, "html_preview")
        optional = dag.build_resolution_snapshot(self.pack, html, self.workflow)
        self.assertEqual(optional["workflow"], dict(workflow_id="illustration", trigger_intent="illustration"))
        self.assertEqual(optional["artifact"], dict(artifact_id="html_preview", delivery_form="html_preview"))
        self.assertNotIn("artifact", dag.build_resolution_snapshot(self.pack))

    def test_snapshot_records_selected_quality_rules(self):
        snapshot = dag.build_resolution_snapshot(
            self.pack, self.script,
            quality_rule_ids=("project_authority", "knowledge_collision", "craft_benchmark"),
        )
        self.assertEqual(
            [(rule["check_id"], rule["stage_id"], rule["blocking_policy"])
             for rule in snapshot["quality_rules"]],
            [
                ("project_authority", "preflight", "hard_block"),
                ("knowledge_collision", "collision_check", "hard_block"),
                ("craft_benchmark", "qa", "require_user_confirmation"),
            ],
        )
        for rule in snapshot["quality_rules"]:
            self.assertIn("script", rule["artifact_ids"])

    def test_snapshot_rejects_unknown_quality_rules(self):
        with self.assertRaises(dag.StageDagError):
            dag.build_resolution_snapshot(
                self.pack, self.script, quality_rule_ids=("unknown",)
            )

    def test_builder_rejects_foreign_or_input_only_descriptors(self):
        shortdrama = resolve_type_pack(load_type_registry(), "shortdrama")
        for pack, artifact, workflow in ((shortdrama, self.script, None),
                                         (shortdrama, None, self.workflow),
                                         (self.pack, resolve_artifact(self.pack, "positioning"), None),
                                         (self.pack, replace(self.script, depends_on=("positioning",)), None)):
            with self.subTest(pack=pack.medium_id), self.assertRaises(dag.StageDagError):
                dag.build_resolution_snapshot(pack, artifact, workflow)

    def test_multiple_delivery_forms_require_explicit_choice(self):
        script = replace(self.script, delivery_forms=("page_script", "outline"))
        pack = replace(self.pack, artifact_types=tuple(script if a.artifact_id == "script" else a for a in self.pack.artifact_types))
        with self.assertRaises(dag.StageDagError):
            dag.build_resolution_snapshot(pack, script)
        self.assertEqual(dag.build_resolution_snapshot(pack, script, delivery_form="outline")["artifact"]["delivery_form"], "outline")

    def test_manifest_rejects_invalid_target_form_workflow_and_policy(self):
        base = dag.build_resolution_snapshot(self.pack, self.script)
        mutations = [
            lambda s: s["artifact"].update(artifact_id="outline"),
            lambda s: s["artifact"].update(delivery_form="unknown"),
            lambda s: s["artifact"].update(extra=True),
            lambda s: s["type_pack"].update(workflow_policy="wrong"),
            lambda s: s.update(workflow=dict(workflow_id="illustration", trigger_intent="wrong")),
            lambda s: s.update(workflow=dict(workflow_id="unknown", trigger_intent="illustration")),
        ]
        for index, mutation in enumerate(mutations):
            snapshot = copy.deepcopy(base)
            mutation(snapshot)
            with self.subTest(index=index), self.assertRaises(dag.StageDagError):
                self.manifest(snapshot)
        with self.assertRaises(dag.StageDagError):
            dag.attach_context(dag._creation_template_manifest(),
                               CreativeContext("picturebook", project_id="p1", delivery_form="outline"), base)

    def test_manifest_rejects_malformed_current_version_quality_rules(self):
        snapshot = dag.build_resolution_snapshot(
            self.pack, self.script,
            quality_rule_ids=("project_authority",),
        )
        mutations = [
            lambda s: s["quality_rules"][0].update(check_id="unknown"),
            lambda s: s["quality_rules"][0].update(stage_id="qa"),
            lambda s: s["quality_rules"][0].update(blocking_policy="silent"),
            lambda s: s["quality_rules"].clear(),
        ]
        for index, mutation in enumerate(mutations):
            broken = copy.deepcopy(snapshot)
            mutation(broken)
            with self.subTest(index=index), self.assertRaises(dag.StageDagError):
                self.manifest(broken)

    def test_optional_workflow_snapshot_uses_separate_illustration_run(self):
        html = resolve_workflow_artifact(self.workflow, "html_preview")
        manifest = dag.attach_context(dag._illustration_template_manifest(), CreativeContext("picturebook", project_id="p1"),
                                      dag.build_resolution_snapshot(self.pack, html, self.workflow))
        self.assertEqual(dag.validate_manifest(manifest), manifest)

    def test_plan_task_and_fallback_snapshots_are_isolated(self):
        manifest = self.manifest()
        original = copy.deepcopy(manifest)
        outputs = [codex.build_dispatch_plan(manifest), codex.build_sequential_fallback(manifest)]
        for output in outputs:
            self.assertEqual(output["resolution_snapshot"], manifest["resolution_snapshot"])
            output["resolution_snapshot"]["artifact"]["artifact_id"] = "changed"
        task = codex.format_task_envelope(manifest, manifest["stages"][0])
        task["inputs"]["run_context"]["resolution_snapshot"]["artifact"]["artifact_id"] = "changed"
        self.assertEqual(manifest, original)

    def test_revision_deep_copies_snapshot_and_legacy_does_not_gain_fields(self):
        for typed in (True, False):
            manifest = self.manifest() if typed else dag._creation_template_manifest()
            manifest["project_root"] = str(REPO_ROOT)
            parent = revision_parent(manifest)
            revision = dag.build_revision_manifest(parent, [{"issue": "hook", "instruction": "revise"}],
                                                   "plugins/picturebook-screenwriter/config/type-packs.json", "new-revision")
            self.assertEqual(revision["revision_of_run_id"], parent["run_id"])
            if typed:
                snapshot = revision["resolution_snapshot"]
                self.assertEqual(snapshot["type_pack"], parent["resolution_snapshot"]["type_pack"])
                self.assertEqual(snapshot["artifact"], parent["resolution_snapshot"]["artifact"])
                self.assertEqual([r["check_id"] for r in snapshot["quality_rules"]],
                                 ["project_authority", "knowledge_collision", "craft_benchmark"])
                revision["resolution_snapshot"]["artifact"]["artifact_id"] = "changed"
                self.assertEqual(parent["resolution_snapshot"]["artifact"]["artifact_id"], "script")
            else:
                self.assertNotIn("context", revision)
                self.assertNotIn("resolution_snapshot", revision)

    def test_historical_and_foundation_snapshots_are_read_without_rewriting(self):
        old = dict(type_pack=dict(medium_id="picturebook", version="0.5.1"))
        self.assertEqual(self.manifest(old)["resolution_snapshot"], old)
        archived = dag.build_resolution_snapshot(self.pack, self.script)
        archived["type_pack"]["version"] = "archived-v0"
        self.assertEqual(self.manifest(archived)["resolution_snapshot"], archived)


if __name__ == "__main__":
    unittest.main(verbosity=2)
