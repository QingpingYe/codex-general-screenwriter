import copy
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import stage_dag as dag
import stage_dag_codex as codex
import type_registry as tr
from screenwriter_context import CreativeContext


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.pack=tr.resolve_type_pack(tr.load_type_registry(),'picturebook')
        self.script=tr.resolve_artifact(self.pack,'script')

    def typed(self, medium='picturebook', *, artifact='script', snapshot=None, illustration=False):
        m=dag._illustration_template_manifest() if illustration else dag._creation_template_manifest()
        m['artifact_type']=artifact
        return dag.attach_context(m,CreativeContext(medium,project_id='p1'),snapshot)

    def test_planned_media_have_no_public_dag_execution_entry(self):
        film=self.typed('film')
        self.assertEqual(dag.validate_manifest(film),film)
        for action in (dag.ready_stages,dag.next_batches,dag.parallel_batches,dag.resolve_stage_decisions,
                       lambda m: dag.transition_stage(m,'session_init','ready')):
            with self.subTest(action=action),self.assertRaises(tr.TypePackNotExecutableError):
                action(film)

    def test_historical_snapshots_are_readable_but_not_dispatchable(self):
        for snapshot in (
            {'type_pack':{'medium_id':'picturebook','version':'0.5.1'}},
            dag.build_resolution_snapshot(self.pack,self.script),
        ):
            snapshot=copy.deepcopy(snapshot)
            snapshot['type_pack']['version']='archived-v0'
            m=self.typed(snapshot=snapshot)
            self.assertEqual(dag.validate_manifest(m),m)
            for action in (codex.build_dispatch_plan,dag.next_batches):
                with self.subTest(action=action),self.assertRaises(dag.StageDagError):
                    action(m)

    def test_explicit_context_rejects_input_only_and_unknown_targets(self):
        for target in ('positioning','not_an_artifact','html_preview'):
            m=self.typed(artifact=target)
            with self.subTest(target=target),self.assertRaises(dag.StageDagError):
                codex.build_dispatch_plan(m)

    def test_optional_workflow_cannot_run_with_core_stages(self):
        workflow=tr.resolve_workflow(self.pack,'illustration')
        html=tr.resolve_workflow_artifact(workflow,'html_preview')
        snapshot=dag.build_resolution_snapshot(self.pack,html,workflow)
        m=self.typed(artifact='illustration',snapshot=snapshot)
        self.assertEqual(dag.validate_manifest(m),m)
        with self.assertRaises(dag.StageDagError):
            codex.build_dispatch_plan(m)

    def test_optional_workflow_requires_explicit_script_provenance(self):
        workflow=tr.resolve_workflow(self.pack,'illustration')
        html=tr.resolve_workflow_artifact(workflow,'html_preview')
        snapshot=dag.build_resolution_snapshot(self.pack,html,workflow)
        m=self.typed(artifact='illustration',snapshot=snapshot,illustration=True)
        self.assertEqual(dag.validate_manifest(m),m)
        with self.assertRaises(dag.StageDagError):
            codex.build_dispatch_plan(m)
        for status in ('draft','unverified'):
            invalid=copy.deepcopy(m)
            invalid['resolution_snapshot']['workflow_inputs']=[
                {'artifact_id':'script','status':status,'ref':'picturebook/script_v1.md'}]
            with self.subTest(status=status),self.assertRaises(dag.StageDagError):
                codex.build_dispatch_plan(invalid)
        good=copy.deepcopy(m)
        good['resolution_snapshot']['workflow_inputs']=[
            {'artifact_id':'script','status':'approved','ref':'picturebook/script_v1.md'}]
        self.assertEqual(codex.build_dispatch_plan(good)['status'],'ready')
        supplied=copy.deepcopy(m)
        supplied['resolution_snapshot']['workflow_inputs']=[
            {'artifact_id':'script','status':'user_supplied','ref':'picturebook/user_script.md',
             'user_confirmation':True}]
        self.assertEqual(codex.build_dispatch_plan(supplied)['status'],'ready')

    def test_artifact_and_stage_alias_collision_rejected_at_load(self):
        payload=json.loads((ROOT/'config/type-packs.json').read_text(encoding='utf-8'))
        core=payload['packs'][0]
        next(a for a in core['artifact_types'] if a['artifact_id']=='script')['aliases']=['shared-name']
        next(s for s in core['stages'] if s['stage_id']=='qa')['aliases']=['shared-name']
        with self.assertRaises(tr.TypeRegistryError):
            tr.parse_type_registry(payload)


if __name__=='__main__':
    unittest.main(verbosity=2)
