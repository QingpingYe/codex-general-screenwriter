import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PLUGIN_SCRIPTS = SCRIPTS.parents[2] / "scripts"
for path in (str(PLUGIN_SCRIPTS), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from knowledge_scope import (
    KnowledgeResolution,
    build_scope_ref,
    build_dependency_record,
    resolve_knowledge,
)
from load_knowledge import (
    ConflictReport,
    KnowledgeEvidence,
    KnowledgeEvidenceBundle,
    KnowledgeQuery,
    bundle_to_dict,
)
from scope_model import ScopeRef
from scope_pages import ScopeEnvelope
from screenwriter_context import CreativeContext


def make_scope(scope_type, scope_id, authority):
    return ScopeEnvelope(
        schema_version=2,
        scope_type=scope_type,
        scope_id=scope_id,
        authority=authority,
        medium_id="shortdrama",
    )


def make_evidence(key, scope=None, authority="system"):
    return KnowledgeEvidence(
        key=key,
        doc_token=f"doc-{key}",
        revision_id=7,
        title=key,
        content=f"# {key}\n\n正文。",
        source_revisions={"source": "r1"},
        scope=scope,
    )


def make_bundle(items):
    return KnowledgeEvidenceBundle(
        items=tuple(items),
        warnings=(),
        offline=False,
        fetched_at="2026-10-10T00:00:00+08:00",
    )


def make_query(scope_ref):
    return KnowledgeQuery(project_id="p1", scope_ref=scope_ref)


class BuildScopeRefTests(unittest.TestCase):
    def test_scope_ref_is_built_from_creative_context(self):
        context = CreativeContext(
            "shortdrama", ("mystery",),
            series_id="s1", project_id="p1", episode_id="e1",
        )
        ref = build_scope_ref(context)
        self.assertEqual(ref.medium_id, "shortdrama")
        self.assertEqual(ref.genre_ids, ("mystery",))
        self.assertEqual(ref.series_id, "s1")
        self.assertEqual(ref.project_id, "p1")
        self.assertEqual(ref.episode_id, "e1")
        self.assertIsNone(ref.task_id)


class ResolveKnowledgeTests(unittest.TestCase):
    def test_lower_project_fact_wins_without_hiding_series_conflict(self):
        project_page = make_evidence(
            "s1/p1/hook_rules", make_scope("project", "p1", "project"))
        series_page = make_evidence(
            "s1/p9/hook_rules", make_scope("series", "s1", "series"))
        bundle = make_bundle([project_page, series_page])
        query = make_query(ScopeRef(series_id="s1", project_id="p1",
                                    medium_id="shortdrama"))

        resolution = resolve_knowledge(bundle, query)

        self.assertEqual(resolution.matches, (project_page,))
        self.assertEqual(
            resolution.conflicts,
            (ConflictReport(
                scope_type="project",
                scope_id="p1",
                reason="same topic claimed by multiple scope nodes; nearest scope wins",
                keys=("s1/p1/hook_rules", "s1/p9/hook_rules"),
            ),),
        )

    def test_user_experiment_cannot_override_system_authority(self):
        system_page = make_evidence(
            "s1/p1/authority_rules", make_scope("project", "p1", "system"))
        experiment_page = make_evidence(
            "s1/p9/authority_rules", make_scope("series", "s1", "user_experiment"))
        bundle = make_bundle([system_page, experiment_page])
        query = make_query(ScopeRef(series_id="s1", project_id="p1",
                                    medium_id="shortdrama"))

        resolution = resolve_knowledge(bundle, query)

        self.assertIn(system_page, resolution.matches)
        self.assertIn(experiment_page, resolution.rejected)
        self.assertNotIn(experiment_page, resolution.matches)

    def test_v1_page_without_scope_metadata_still_loads(self):
        v1_page = make_evidence("s1/p1/worldview")
        bundle = make_bundle([v1_page])
        query = make_query(ScopeRef(project_id="p1"))

        resolution = resolve_knowledge(bundle, query)

        self.assertIn(v1_page, resolution.matches)
        self.assertEqual(resolution.knowledge_schema, "v1")

    def test_matches_ordered_nearest_scope_first(self):
        episode_page = make_evidence(
            "s1/p9/hook_rules", make_scope("episode", "e1", "project"))
        project_page = make_evidence(
            "s1/p1/outline", make_scope("project", "p1", "project"))
        medium_page = make_evidence(
            "s1/p9/outline_medium", make_scope("medium", "shortdrama", "type_pack"))
        bundle = make_bundle([medium_page, project_page, episode_page])
        query = make_query(ScopeRef(series_id="s1", project_id="p1",
                                    episode_id="e1", medium_id="shortdrama"))

        resolution = resolve_knowledge(bundle, query)

        self.assertEqual(
            resolution.matches,
            (episode_page, project_page, medium_page),
        )
        self.assertEqual(resolution.knowledge_schema, "knowledge-scope-v2")

    def test_resolution_does_not_mutate_input_bundle(self):
        project_page = make_evidence(
            "s1/p1/hook_rules", make_scope("project", "p1", "project"))
        series_page = make_evidence(
            "s1/p9/hook_rules", make_scope("series", "s1", "series"))
        bundle = make_bundle([project_page, series_page])
        query = make_query(ScopeRef(series_id="s1", project_id="p1"))
        before = bundle_to_dict(bundle)

        resolve_knowledge(bundle, query)

        self.assertEqual(bundle_to_dict(bundle), before)

    def test_page_outside_scope_chain_is_rejected(self):
        inside = make_evidence(
            "s1/p1/hook_rules", make_scope("project", "p1", "project"))
        outside = make_evidence(
            "s9/p9/hook_rules", make_scope("project", "p9", "project"))
        bundle = make_bundle([inside, outside])
        query = make_query(ScopeRef(series_id="s1", project_id="p1"))

        resolution = resolve_knowledge(bundle, query)

        self.assertEqual(resolution.matches, (inside,))
        self.assertIn(outside, resolution.rejected)


class DependencyRecordTests(unittest.TestCase):
    def test_dependency_record_carries_v2_scope_snapshot(self):
        project_page = make_evidence(
            "s1/p1/hook_rules", make_scope("project", "p1", "project"))
        series_page = make_evidence(
            "s1/p9/hook_rules", make_scope("series", "s1", "series"))
        bundle = make_bundle([project_page, series_page])
        query = make_query(ScopeRef(series_id="s1", project_id="p1"))
        resolution = resolve_knowledge(bundle, query)

        record = build_dependency_record(bundle, "run-1", "script", resolution)

        self.assertEqual(record.knowledge_schema, "knowledge-scope-v2")
        self.assertEqual(record.artifact_id, "run-1")
        self.assertEqual(record.artifact_type, "script")
        self.assertEqual(
            [item["key"] for item in record.evidence],
            ["s1/p1/hook_rules"],
        )
        self.assertEqual(
            [dict(node) for node in record.scope_chain],
            [
                {"scope_type": "project", "scope_id": "p1", "authority": "system"},
                {"scope_type": "series", "scope_id": "s1", "authority": "system"},
                {"scope_type": "global", "scope_id": "all", "authority": "system"},
            ],
        )

    def test_build_dependency_record_keeps_v1_path(self):
        page = make_evidence("s1/p1/worldview")
        bundle = make_bundle([page])

        record = build_dependency_record(bundle, "run-1", "script")

        self.assertEqual(record.knowledge_schema, "v1")
        self.assertEqual(record.scope_chain, ())


if __name__ == "__main__":
    unittest.main()
