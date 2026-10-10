import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_dag
from screenwriter_context import CreativeContext
from type_registry import load_type_registry, resolve_type_pack


class StageDagContextTests(unittest.TestCase):
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

    def test_legacy_manifest_infers_picturebook_context_without_mutation(self):
        manifest = stage_dag._creation_template_manifest()
        context = stage_dag.extract_context(manifest)
        self.assertEqual(context.medium_id, "picturebook")
        self.assertNotIn("context", manifest)

    def test_explicit_null_context_is_rejected(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["context"] = None
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.validate_manifest(manifest)

    def test_resolution_snapshot_requires_context_and_known_fields(self):
        legacy_with_snapshot = stage_dag._creation_template_manifest()
        legacy_with_snapshot["resolution_snapshot"] = {
            "type_pack": {"medium_id": "picturebook", "version": "0.5.1"}
        }
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.validate_manifest(legacy_with_snapshot)

        manifest = stage_dag._creation_template_manifest()
        manifest = stage_dag.attach_context(
            manifest,
            CreativeContext("picturebook", project_id="p1"),
            {"type_pack": {"medium_id": "picturebook", "version": "0.5.1"}},
        )
        manifest["resolution_snapshot"]["unexpected"] = True
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.validate_manifest(manifest)

    def test_new_context_requires_project_id(self):
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.attach_context(
                stage_dag._creation_template_manifest(),
                CreativeContext("shortdrama"),
                {"type_pack": {"medium_id": "shortdrama", "version": "shortdrama-v1"}},
            )

    def test_explicit_context_in_manifest_requires_project_id(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["context"] = {"medium_id": "shortdrama"}
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.validate_manifest(manifest)

    def test_attach_context_is_deep_copy_and_validates_snapshot(self):
        manifest = stage_dag._creation_template_manifest()
        context = CreativeContext("shortdrama", ("mystery",), project_id="p1")
        enriched = stage_dag.attach_context(
            manifest,
            context,
            {"type_pack": {"medium_id": "shortdrama", "version": "shortdrama-v1"}},
        )
        self.assertNotIn("context", manifest)
        self.assertEqual(enriched["context"]["medium_id"], "shortdrama")
        self.assertEqual(stage_dag.validate_manifest(enriched), enriched)

    def test_rejects_snapshot_for_a_different_medium(self):
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.attach_context(
                stage_dag._creation_template_manifest(),
                CreativeContext("shortdrama", project_id="p1"),
                {"type_pack": {"medium_id": "tv_longform", "version": "tv_longform-v1"}},
            )

    def test_revision_copies_context_snapshot_and_updates_lineage(self):
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
            artifact_ref="plugins/general-screenwriter/config/type-packs.json",
            run_id="foundation-revision-0002",
        )
        self.assertEqual(revision["context"], parent["context"])
        self.assertEqual(
            {key: revision["resolution_snapshot"]["type_pack"][key]
             for key in parent["resolution_snapshot"]["type_pack"]},
            parent["resolution_snapshot"]["type_pack"],
        )
        self.assertEqual(
            [item["check_id"] for item in revision["resolution_snapshot"]["quality_rules"]],
            ["project_authority", "knowledge_collision", "craft_benchmark"],
        )
        self.assertNotEqual(revision["run_id"], parent["run_id"])
        self.assertEqual(revision["revision_of_run_id"], parent["run_id"])


SKILL_SNAPSHOT = {
    "skill_id": "project-hook-checklist",
    "version": "1.0.0",
    "authority": "project_skill",
    "scopes": [{"scope_type": "project", "project_id": "p1"}],
    "stage_id": "qa",
    "execution_policy": "advisory",
    "status": "active",
    "content_hash": "abc123def456",
}


def _skills_snapshot(**skill_overrides):
    skill = dict(SKILL_SNAPSHOT)
    skill.update(skill_overrides)
    return {
        "type_pack": {"medium_id": "picturebook", "version": "picturebook-v1"},
        "skills": [skill],
    }


class SkillsSnapshotTests(unittest.TestCase):
    def test_build_resolution_snapshot_accepts_skills(self):
        snapshot = stage_dag.build_resolution_snapshot(
            resolve_type_pack(load_type_registry(), "picturebook"),
            skills=[dict(SKILL_SNAPSHOT)],
        )
        self.assertEqual(snapshot["skills"], [SKILL_SNAPSHOT])

    def test_snapshot_skills_are_deep_copied(self):
        skills = [dict(SKILL_SNAPSHOT)]
        snapshot = stage_dag.build_resolution_snapshot(
            resolve_type_pack(load_type_registry(), "picturebook"),
            skills=skills,
        )
        snapshot["skills"][0]["skill_id"] = "mutated"
        self.assertEqual(skills[0]["skill_id"], "project-hook-checklist")

    def test_validate_manifest_accepts_compact_skills_snapshot(self):
        manifest = stage_dag.attach_context(
            stage_dag._creation_template_manifest(),
            CreativeContext("picturebook", project_id="p1"),
            _skills_snapshot(),
        )
        self.assertEqual(stage_dag.validate_manifest(manifest), manifest)

    def test_validate_manifest_rejects_unknown_skill_fields(self):
        snapshot = _skills_snapshot(extra="x")
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.attach_context(
                stage_dag._creation_template_manifest(),
                CreativeContext("picturebook", project_id="p1"),
                snapshot,
            )

    def test_validate_manifest_rejects_missing_content_hash(self):
        skill = dict(SKILL_SNAPSHOT)
        skill.pop("content_hash")
        snapshot = {
            "type_pack": {"medium_id": "picturebook", "version": "picturebook-v1"},
            "skills": [skill],
        }
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag.attach_context(
                stage_dag._creation_template_manifest(),
                CreativeContext("picturebook", project_id="p1"),
                snapshot,
            )

    def test_revision_manifest_inherits_skills_snapshot(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["project_root"] = str(REPO_ROOT)
        manifest = stage_dag.attach_context(
            manifest,
            CreativeContext("picturebook", project_id="p1"),
            _skills_snapshot(),
        )
        for stage_id in ("session_init", "brief_gate", "knowledge_load",
                         "creation_delegate", "preflight", "collision_check",
                         "qa", "qa_synthesis"):
            for status in ("ready", "running", "done"):
                manifest = stage_dag.transition_stage(manifest, stage_id, status)
        for status in ("ready", "running"):
            manifest = stage_dag.transition_stage(manifest, "confirmation_gate", status)
        manifest = stage_dag.transition_stage(
            manifest, "confirmation_gate", "done", outcome="revision_requested")
        parent = stage_dag.finalize_run(manifest, "revision_requested")

        revision = stage_dag.build_revision_manifest(
            parent,
            feedback=[{"issue": "hook", "instruction": "strengthen"}],
            artifact_ref="plugins/general-screenwriter/config/type-packs.json",
            run_id="skills-revision-0002",
        )
        self.assertEqual(
            revision["resolution_snapshot"]["skills"],
            parent["resolution_snapshot"]["skills"],
        )
        revision["resolution_snapshot"]["skills"][0]["skill_id"] = "mutated"
        self.assertEqual(
            parent["resolution_snapshot"]["skills"][0]["skill_id"],
            "project-hook-checklist",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
