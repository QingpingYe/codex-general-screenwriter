import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from knowledge_schema_v2 import (
    KnowledgeMigrationReport,
    ScopePageCandidate,
    build_scope_migration_report,
    parse_scope_page,
    render_scope_page,
    scope_key,
    validate_scope_page,
)
from page_codec import parse_remote_page, render_remote_page
from scope_pages import ScopeEnvelope
from shared_schema import SchemaError


V1_METADATA = {
    "key": "海外绘本/小老鼠迈尔斯/worldview",
    "page_type": "worldview",
    "source_node_tokens": ["src1"],
    "source_revisions": {"src1": "r1"},
    "last_ai_revision_id": 3,
}


def project_scope(**overrides):
    fields = {
        "schema_version": 2,
        "scope_type": "project",
        "scope_id": "p1",
        "authority": "project",
        "medium_id": "shortdrama",
        "genre_ids": ("mystery",),
        "version": 2,
        "depends_on": (),
        "source_refs": ("feishu://node/x",),
        "built_against": {},
        "supersedes": (),
    }
    fields.update(overrides)
    return ScopeEnvelope(**fields)


class ParseScopePageTests(unittest.TestCase):
    def test_v1_page_is_unchanged_when_v2_scope_is_absent(self):
        page = parse_remote_page(render_remote_page("# 标题\n\n正文。\n", V1_METADATA))
        self.assertIsNone(parse_scope_page(page.body, page.metadata))

    def test_v2_scope_requires_consistent_scope_and_page_type(self):
        body = render_scope_page("# 世界观\n\n小老鼠住在森林里。", project_scope())
        with self.assertRaises(SchemaError):
            parse_scope_page(body, V1_METADATA)

    def test_scope_page_round_trip_preserves_envelope(self):
        scope = project_scope()
        body = render_scope_page("# 世界观\n\n小老鼠住在森林里。", scope)
        metadata = {**V1_METADATA, "key": "project/p1/worldview"}
        page = parse_remote_page(render_remote_page(body, metadata))

        parsed = parse_scope_page(page.body, page.metadata)

        self.assertEqual(parsed, scope)

    def test_malformed_authority_is_rejected(self):
        body = (
            "# 标题\n\n## knowledge-scope\n```json\n"
            '{"authority": "root", "schema_version": 2, "scope_id": "p1", '
            '"scope_type": "project", "source_refs": ["x"]}\n```\n'
        )
        metadata = {**V1_METADATA, "key": "project/p1/worldview"}
        with self.assertRaises(SchemaError):
            parse_scope_page(body, metadata)


class ValidateScopePageTests(unittest.TestCase):
    def test_validate_scope_page_returns_candidate(self):
        scope = project_scope()
        body = render_scope_page("# 世界观", scope)
        metadata = {**V1_METADATA, "key": "project/p1/worldview"}
        page = parse_remote_page(render_remote_page(body, metadata))

        candidate = validate_scope_page(page)

        self.assertIsInstance(candidate, ScopePageCandidate)
        self.assertEqual(candidate.key, "project/p1/worldview")
        self.assertEqual(candidate.scope, scope)

    def test_validate_scope_page_rejects_supersedes_cycle(self):
        scope = project_scope(supersedes=("project/p1/worldview",))
        body = render_scope_page("# 世界观", scope)
        metadata = {**V1_METADATA, "key": "project/p1/worldview"}
        page = parse_remote_page(render_remote_page(body, metadata))

        with self.assertRaises(SchemaError):
            validate_scope_page(page)

    def test_validate_scope_page_requires_source_refs(self):
        scope = project_scope(source_refs=())
        body = render_scope_page("# 世界观", scope)
        metadata = {**V1_METADATA, "key": "project/p1/worldview"}
        page = parse_remote_page(render_remote_page(body, metadata))

        with self.assertRaises(SchemaError):
            validate_scope_page(page)


class ScopeKeyTests(unittest.TestCase):
    def test_scope_key_builds_logical_key(self):
        self.assertEqual(scope_key(project_scope(), "worldview"), "project/p1/worldview")
        self.assertEqual(
            scope_key(project_scope(scope_type="medium", scope_id="shortdrama"), "worldview"),
            "medium/shortdrama/worldview",
        )


class MigrationReportTests(unittest.TestCase):
    def test_migration_report_reports_ambiguity_without_rewriting(self):
        inventory = [
            {"key": "海外绘本/小老鼠迈尔斯/worldview", "page_type": "worldview", "scope": None},
            {"key": "project/p1/worldview", "page_type": "worldview", "scope": project_scope()},
            {"key": "海外绘本/小老鼠迈尔斯/characters", "page_type": "characters", "scope": project_scope()},
            {"page_type": "worldview", "scope": None},
        ]
        snapshot = [dict(item) for item in inventory]

        report = build_scope_migration_report(inventory)

        self.assertIsInstance(report, KnowledgeMigrationReport)
        self.assertEqual(report.source_kind, "knowledge_page")
        self.assertEqual(report.source_version, 1)
        self.assertEqual(report.target_version, 2)
        self.assertEqual(
            report.matched,
            ("海外绘本/小老鼠迈尔斯/worldview", "project/p1/worldview"),
        )
        self.assertEqual(report.ambiguous, ("海外绘本/小老鼠迈尔斯/characters",))
        self.assertEqual(report.missing, ("<unnamed>",))
        self.assertEqual(report.rollback, {"mode": "read_only", "writes": 0})
        self.assertEqual([dict(item) for item in inventory], snapshot)


if __name__ == "__main__":
    unittest.main()
