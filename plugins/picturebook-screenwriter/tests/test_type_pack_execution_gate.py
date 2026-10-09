import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; REPO_ROOT=ROOT.parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
import stage_dag, stage_dag_codex
from screenwriter_context import CreativeContext
from type_registry import TypePackNotExecutableError, load_type_registry, resolve_type_pack

class TypePackExecutionGateTests(unittest.TestCase):
    def manifest_for(self, medium, *, context=True):
        manifest=stage_dag._creation_template_manifest(); manifest['project_root']=str(REPO_ROOT)
        if context:
            manifest=stage_dag.attach_context(manifest,CreativeContext(medium,project_id=f'{medium}-p'),
                {'type_pack':{'medium_id':medium,'version':f'{medium}-v1','workflow_policy':f'{medium}-v1'}})
        return manifest

    def test_planned_medium_rejected_before_plan_fallback_and_task(self):
        for medium in ('shortdrama','tv_longform'):
            manifest=self.manifest_for(medium)
            for operation in (
                lambda: stage_dag_codex.build_dispatch_plan(manifest),
                lambda: stage_dag_codex.build_sequential_fallback(manifest),
                lambda: stage_dag_codex.format_task_envelope(manifest,manifest['stages'][0]),
            ):
                with self.subTest(medium=medium, operation=operation), self.assertRaises(TypePackNotExecutableError):
                    operation()

    def test_legacy_and_active_picturebook_remain_dispatchable(self):
        legacy=self.manifest_for('picturebook',context=False)
        self.assertEqual(stage_dag_codex.build_dispatch_plan(legacy)['status'],'ready')
        active=self.manifest_for('picturebook')
        self.assertEqual(stage_dag_codex.build_dispatch_plan(active)['context']['medium_id'],'picturebook')

    def test_unknown_explicit_medium_does_not_fallback_to_picturebook(self):
        manifest=self.manifest_for('picturebook')
        manifest['context']['medium_id']='unknown'
        with self.assertRaises(stage_dag.StageDagError):
            stage_dag_codex.build_dispatch_plan(manifest)

    def test_optional_illustration_workflow_has_separate_route(self):
        pack=resolve_type_pack(load_type_registry(),'picturebook')
        workflow=stage_dag.resolve_workflow(pack,'illustration')
        core={s['stage_id'] for s in stage_dag._creation_template_manifest()['stages']}
        optional={s.stage_id for s in workflow.stages}
        self.assertTrue(core.isdisjoint(optional))
        self.assertFalse(workflow.required)
        self.assertFalse(workflow.blocks_core_completion)
        self.assertEqual([(x.artifact_id,x.required_status) for x in workflow.inputs],[('script','approved')])

if __name__=='__main__': unittest.main(verbosity=2)
