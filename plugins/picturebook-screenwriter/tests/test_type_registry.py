import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import type_registry as tr

CORE = {"positioning", "topic_plan", "worldview", "characters", "outline", "script"}
OPTIONAL = {"asset_registry", "illustration_prompt_payload", "image_asset", "html_preview"}
STAGE_TYPES = {
    "session_init": "session_init",
    "brief_gate": "brief_gate",
    "knowledge_load": "knowledge_load",
    "draft": "creation",
    "preflight": "validation",
    "collision_check": "validation",
    "qa": "validation",
    "qa_synthesis": "synthesis",
    "confirmation_gate": "confirmation",
    "persistence": "persistence",
    "knowledge_reminder": "delivery",
}


def artifact(aid="script", **kwargs):
    result = dict(
        artifact_id=aid, aliases=[], delivery_forms=["script"], depends_on=[],
        origin="workflow_output", input_stage=None, production_stage="draft",
        validation_stages=["qa"], validator=None, exporter=None, status="active",
    )
    result.update(kwargs)
    return result


def stage(sid, **kwargs):
    result = dict(
        stage_id=sid, aliases=[], depends_on=[], consumes_artifact_ids=[],
        produces_artifact_ids=[], validates_artifact_ids=[],
        confirmation_required=False, status="active",
        stage_type="validation", owner="runtime", gate="none",
    )
    result.update(kwargs)
    return result


def with_runtime_semantics(payload):
    for raw in payload["packs"][0]["stages"]:
        raw.update(stage_type=STAGE_TYPES[raw["stage_id"]], owner="runtime", gate="none")
    return payload


def quality_rule(**kwargs):
    result = dict(
        check_id="project_authority", artifact_ids=["script"],
        stage_id="qa", blocking_policy="hard_block",
        validator=None,
    )
    result.update(kwargs)
    return result


def valid_payload():
    return {"schema_version": 1, "packs": [dict(
        medium_id="demo", version="demo-v1", aliases=[], legacy_aliases=[],
        delivery_forms=["script"], artifact_types=[
            artifact("brief", origin="user_input", input_stage="brief_gate",
                     production_stage=None, validation_stages=[]),
            artifact(),
        ], stages=[
            stage("brief_gate", consumes_artifact_ids=["brief"]),
            stage("draft", depends_on=["brief_gate"], consumes_artifact_ids=["brief"],
                  produces_artifact_ids=["script"]),
            stage("qa", depends_on=["draft"], validates_artifact_ids=["script"]),
        ], optional_workflows=[], workflow_policy="demo-v1", status="active",
        validators=[], exporters=[], capabilities=[],
    )]}


class TypeRegistryTests(unittest.TestCase):
    def test_loads_three_mediums_all_active(self):
        registry = tr.load_type_registry()
        self.assertEqual({p.medium_id for p in registry.packs},
                         {"picturebook", "shortdrama", "tv_longform"})
        self.assertEqual({p.medium_id for p in registry.packs if p.status == "active"},
                         {"picturebook", "shortdrama", "tv_longform"})
        with self.assertRaises(tr.TypeRegistryError):
            tr.resolve_type_pack(registry, "film")

    def test_picturebook_core_contract_is_not_an_illustration_pipeline(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picturebook-screenwriter")
        self.assertEqual(pack.version, "picturebook-v1")
        self.assertEqual(set(pack.artifact_ids), CORE)
        positioning = tr.resolve_artifact(pack, "positioning")
        self.assertEqual((positioning.origin, positioning.input_stage, positioning.production_stage),
                         ("user_input", "brief_gate", None))
        self.assertEqual(tr.resolve_stage(pack, "brief_gate").produces_artifact_ids, ())
        self.assertEqual(set(tr.resolve_stage(pack, "drafting").produces_artifact_ids), CORE - {"positioning"})
        for aid in CORE - {"positioning"}:
            target = tr.assert_core_artifact_target(pack, aid)
            self.assertEqual(target.production_stage, "creation_delegate")
            self.assertEqual(target.depends_on, ())
            self.assertIn("preflight", target.validation_stages)
            self.assertIn("qa", target.validation_stages)
        for aid in ("positioning", *OPTIONAL):
            with self.subTest(aid=aid), self.assertRaises(tr.ArtifactContractError):
                tr.assert_core_artifact_target(pack, aid)

    def test_optional_workflow_is_isolated_and_requires_approved_script(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picture book")
        workflow = tr.resolve_workflow(pack, "illustration")
        self.assertFalse(workflow.required)
        self.assertFalse(workflow.blocks_core_completion)
        self.assertEqual([(i.artifact_id, i.required_status) for i in workflow.inputs], [("script", "approved")])
        self.assertEqual({a.artifact_id for a in workflow.artifact_types}, OPTIONAL)
        self.assertTrue(set(s.stage_id for s in workflow.stages).isdisjoint(s.stage_id for s in pack.stages))
        self.assertEqual({s.stage_id for s in workflow.stages if s.confirmation_required},
                         {"asset_confirmation", "asset_final_confirmation"})
        expected = dict(asset_registry="asset_extraction", illustration_prompt_payload="asset_preproduction",
                        image_asset="illustration_generation", html_preview="html_export")
        for aid, producer in expected.items():
            self.assertEqual(tr.resolve_workflow_artifact(workflow, aid).production_stage, producer)
        self.assertEqual(tr.resolve_workflow_artifact(workflow, "preview").artifact_id, "html_preview")

    def test_aliases_and_distinct_unknown_errors(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "绘本")
        self.assertEqual(tr.resolve_artifact(pack, " FINAL-SCRIPT ").artifact_id, "script")
        for resolver, exception in ((tr.resolve_artifact, tr.ArtifactContractError),
                                    (tr.resolve_stage, tr.StageContractError),
                                    (tr.resolve_workflow, tr.WorkflowContractError)):
            with self.subTest(resolver=resolver.__name__), self.assertRaises(exception):
                resolver(pack, "unknown")
        with self.assertRaises(tr.TypeRegistryError):
            tr.resolve_type_pack(tr.load_type_registry(), "unknown")

    def test_planned_is_readable_but_never_executable(self):
        registry = tr.load_type_registry()
        for medium in ("shortdrama", "tv_longform"):
            pack = replace(tr.resolve_type_pack(registry, medium), status="planned")
            with self.subTest(medium=medium), self.assertRaises(tr.TypePackNotExecutableError):
                tr.assert_type_pack_executable(pack)

    def test_new_empty_active_pack_is_rejected(self):
        payload = valid_payload()
        payload["packs"][0].update(artifact_types=[], stages=[])
        payload["packs"][0].pop("optional_workflows")
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(payload)

    def test_legacy_nonempty_strings_remain_readable_not_full_v1(self):
        payload = {"schema_version": 1, "packs": [dict(
            medium_id="picturebook", aliases=[], delivery_forms=["page_script"],
            artifact_types=["script", "outline"], workflow_policy="picturebook-v1", status="active",
        )]}
        pack = tr.parse_type_registry(payload).packs[0]
        self.assertEqual(pack.artifact_ids, ("script", "outline"))
        with self.assertRaises(tr.TypePackNotExecutableError):
            tr.assert_type_pack_executable(pack)

    def test_missing_version_and_false_schema_version_are_rejected(self):
        for mutation in (lambda p: p["packs"][0].pop("version"),
                         lambda p: p.update(schema_version=True)):
            payload = valid_payload()
            mutation(payload)
            with self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)

    def test_core_production_and_validation_directions_must_agree(self):
        mutations = [
            lambda p: p["artifact_types"][0].update(production_stage="brief_gate"),
            lambda p: p["artifact_types"][1].update(production_stage="unknown"),
            lambda p: p["stages"][1].update(produces_artifact_ids=[]),
            lambda p: p["stages"][2].update(validates_artifact_ids=[]),
            lambda p: p["artifact_types"][1].update(validation_stages=["brief_gate"]),
        ]
        for index, mutation in enumerate(mutations):
            payload = valid_payload()
            mutation(payload["packs"][0])
            with self.subTest(index=index), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)

    def test_rejects_bad_references_cycles_and_delivery_forms(self):
        mutations = [
            lambda p: p["artifact_types"][1].update(depends_on=["unknown"]),
            lambda p: p["artifact_types"][1].update(depends_on=["script"]),
            lambda p: p["artifact_types"][1].update(delivery_forms=["unknown"]),
            lambda p: p["stages"][1].update(depends_on=["unknown"]),
            lambda p: p["stages"][1].update(depends_on=["qa"]),
            lambda p: p["stages"][2].update(consumes_artifact_ids=["unknown"]),
            lambda p: p["artifact_types"][1].update(validator="unregistered"),
            lambda p: p["artifact_types"][1].update(exporter="unregistered"),
            lambda p: p["stages"][2].update(status="planned"),
        ]
        for index, mutation in enumerate(mutations):
            payload = valid_payload()
            mutation(payload["packs"][0])
            with self.subTest(index=index), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)

    def test_artifact_dependency_need_not_be_an_earlier_stage(self):
        payload = valid_payload()
        pack = payload["packs"][0]
        pack["artifact_types"].append(artifact("second", depends_on=["script"]))
        pack["stages"][1]["produces_artifact_ids"].append("second")
        pack["stages"][2]["validates_artifact_ids"].append("second")
        parsed = tr.parse_type_registry(payload).packs[0]
        self.assertEqual(tr.resolve_artifact(parsed, "second").depends_on, ("script",))

    def test_duplicate_names_and_reserved_aliases_are_rejected(self):
        mutations = [
            lambda p: p["aliases"].extend(["same", " SAME "]),
            lambda p: p["artifact_types"][1].update(aliases=["brief"]),
            lambda p: p["artifact_types"][1].update(aliases=["demo"]),
            lambda p: p["stages"][1].update(aliases=["qa"]),
            lambda p: p["stages"][1].update(aliases=["demo"]),
            lambda p: p["artifact_types"].append(copy.deepcopy(p["artifact_types"][1])),
            lambda p: p["stages"].append(copy.deepcopy(p["stages"][1])),
        ]
        for index, mutation in enumerate(mutations):
            payload = valid_payload()
            mutation(payload["packs"][0])
            with self.subTest(index=index), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)

    def test_optional_workflow_cannot_block_or_mix_with_core(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picturebook")
        workflow = tr.resolve_workflow(pack, "illustration")
        for broken in (replace(workflow, blocks_core_completion=True), replace(workflow, required=True)):
            with self.subTest(workflow=broken), self.assertRaises(tr.WorkflowContractError):
                tr.validate_type_contract(replace(pack, optional_workflows=(broken,)))
        with self.assertRaises(tr.StageContractError):
            tr.validate_type_contract(replace(pack, stages=pack.stages + workflow.stages))

    def test_alias_collision_with_legacy_entry_and_bad_status_are_rejected(self):
        payload = valid_payload()
        payload["packs"][0]["aliases"] = ["picturebook-screenwriter"]
        payload["packs"].append(dict(medium_id="shortdrama", aliases=["picturebook-screenwriter"],
                                    delivery_forms=["episode_script"], artifact_types=[],
                                    workflow_policy="shortdrama-v1", status="planned"))
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(payload)

    def test_full_active_v1_requires_runtime_semantics(self):
        payload = with_runtime_semantics(valid_payload())
        for index in range(3):
            field = ("stage_type", "owner", "gate")[index]
            target = payload["packs"][0]["stages"][1]
            saved = target.pop(field)
            with self.subTest(field=field), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)
            target[field] = saved

    def test_picturebook_declares_seed_quality_rules(self):
        pack = tr.resolve_type_pack(tr.load_type_registry(), "picturebook")
        self.assertEqual(
            [(r.check_id, r.stage_id, r.blocking_policy) for r in pack.quality_rules],
            [
                ("project_authority", "preflight", "hard_block"),
                ("knowledge_collision", "collision_check", "hard_block"),
                ("craft_benchmark", "qa", "require_user_confirmation"),
            ],
        )

    def test_quality_rules_validate_pack_references(self):
        payload = valid_payload()
        payload["packs"][0]["quality_rules"] = [quality_rule()]
        tr.parse_type_registry(payload)
        duplicate = valid_payload()
        duplicate["packs"][0]["quality_rules"] = [
            quality_rule(check_id="same"), quality_rule(check_id="same"),
        ]
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(duplicate)
        mutations = [
            lambda p: p["quality_rules"][0].update(artifact_ids=["unknown"]),
            lambda p: p["quality_rules"][0].update(artifact_ids=["brief"]),
            lambda p: p["quality_rules"][0].update(stage_id="draft"),
            lambda p: p["quality_rules"][0].update(validator="unregistered"),
            lambda p: p["quality_rules"][0].update(blocking_policy="silent"),
        ]
        for index, mutation in enumerate(mutations):
            payload = valid_payload()
            payload["packs"][0]["quality_rules"] = [quality_rule()]
            mutation(payload["packs"][0])
            with self.subTest(index=index), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)
        for value in (None, [], "bad"):
            payload = valid_payload()
            payload["packs"][0]["status"] = value
            with self.subTest(status=value), self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
