import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
USER_SKILL_SCRIPTS = str(ROOT / "skills" / "user-skill-hub" / "scripts")
if USER_SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, USER_SKILL_SCRIPTS)

import stage_dag
import stage_dag_codex
import type_registry as type_registry
from creative_run_builder import CreativeRunRequest, build_creative_run
from screenwriter_context import CreativeContext
from user_skill_hub import UserSkill, used_user_skill_record


def _user_skill_record(skill_id="user-checklist"):
    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        (directory / "SKILL.md").write_text(
            f"# {skill_id}\n\nUse this checklist.\n", encoding="utf-8"
        )
        skill = UserSkill(
            directory=directory,
            manifest={
                "skill_id": skill_id,
                "title": "Checklist",
                "user_name": "lvan",
                "updated_at": "2026-10-10T00:00:00Z",
                "content": "SKILL.md",
            },
            content="SKILL.md",
        )
        return used_user_skill_record(skill)


class UserSkillRunIntegrationTests(unittest.TestCase):
    @staticmethod
    def _request(**overrides):
        pack = type_registry.resolve_type_pack(
            type_registry.load_type_registry(), "picturebook"
        )
        values = dict(
            type_pack=pack,
            context=CreativeContext(
                "picturebook", project_id="p1", delivery_form="page_script"
            ),
            intent="creation",
            target="script",
            run_id="user-skill-run-1",
            project_root=str(REPO_ROOT),
        )
        values.update(overrides)
        return CreativeRunRequest(**values)

    def test_new_typed_run_contains_and_isolates_used_user_skill(self):
        record = _user_skill_record()
        manifest = build_creative_run(self._request(
            used_user_skills=[record],
        ))

        self.assertEqual(
            manifest["resolution_snapshot"]["used_user_skills"], [record]
        )
        plan = stage_dag_codex.build_dispatch_plan(manifest)
        task = stage_dag_codex.format_task_envelope(
            manifest, manifest["stages"][0]
        )
        self.assertEqual(
            plan["resolution_snapshot"]["used_user_skills"], [record]
        )
        self.assertEqual(
            task["inputs"]["run_context"]["resolution_snapshot"][
                "used_user_skills"
            ],
            [record],
        )

        plan["resolution_snapshot"]["used_user_skills"][0]["skill_id"] = "mutated"
        task["inputs"]["run_context"]["resolution_snapshot"][
            "used_user_skills"
        ][0]["user_name"] = "mutated"
        self.assertEqual(
            manifest["resolution_snapshot"]["used_user_skills"][0]["skill_id"],
            "user-checklist",
        )
        self.assertEqual(
            manifest["resolution_snapshot"]["used_user_skills"][0]["user_name"],
            "lvan",
        )

    def test_snapshot_builder_deep_copies_used_user_skills(self):
        record = _user_skill_record()
        skills = [record]
        pack = type_registry.resolve_type_pack(
            type_registry.load_type_registry(), "picturebook"
        )
        snapshot = stage_dag.build_resolution_snapshot(
            pack, used_user_skills=skills
        )

        self.assertEqual(snapshot["used_user_skills"], [record])
        snapshot["used_user_skills"][0]["skill_id"] = "mutated"
        self.assertEqual(skills[0]["skill_id"], "user-checklist")

    def test_legacy_snapshot_without_user_skills_remains_unchanged(self):
        manifest = stage_dag._creation_template_manifest()
        manifest["project_root"] = str(REPO_ROOT)
        manifest = stage_dag.attach_context(
            manifest,
            CreativeContext("picturebook", project_id="p1"),
            {"type_pack": {"medium_id": "picturebook",
                           "version": "picturebook-v1"}},
        )

        self.assertNotIn(
            "used_user_skills", manifest["resolution_snapshot"]
        )
        self.assertEqual(stage_dag.validate_manifest(manifest), manifest)

    def test_invalid_used_user_skills_are_rejected(self):
        valid = _user_skill_record()
        missing_user_name = {
            key: value for key, value in valid.items() if key != "user_name"
        }
        unknown_field = dict(valid, extra="x")
        invalid_hash = dict(valid, content_hash="not-sha256")
        for skills in (missing_user_name, unknown_field, invalid_hash):
            with self.subTest(skills=skills):
                with self.assertRaises(stage_dag.StageDagError):
                    build_creative_run(self._request(used_user_skills=[skills]))

    def test_revision_manifest_inherits_used_user_skills_isolated(self):
        record = _user_skill_record()
        parent = build_creative_run(self._request(
            run_id="user-skill-parent-1",
            used_user_skills=[record],
        ))
        for stage in parent["stages"]:
            stage_id = stage["stage_id"]
            if stage_id in {"confirmation_gate", "persistence",
                            "knowledge_reminder"}:
                continue
            for status in ("ready", "running", "done"):
                parent = stage_dag.transition_stage(parent, stage_id, status)
        for status in ("ready", "running"):
            parent = stage_dag.transition_stage(
                parent, "confirmation_gate", status
            )
        parent = stage_dag.transition_stage(
            parent, "confirmation_gate", "done",
            outcome="revision_requested",
        )
        parent = stage_dag.finalize_run(parent, "revision_requested")

        revision = stage_dag.build_revision_manifest(
            parent,
            feedback=[{"issue": "hook", "instruction": "strengthen"}],
            artifact_ref="plugins/general-screenwriter/config/type-packs.json",
            run_id="user-skill-revision-2",
        )

        self.assertEqual(
            revision["resolution_snapshot"]["used_user_skills"], [record]
        )
        revision["resolution_snapshot"]["used_user_skills"][0]["skill_id"] = "mutated"
        self.assertEqual(
            parent["resolution_snapshot"]["used_user_skills"][0]["skill_id"],
            "user-checklist",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
