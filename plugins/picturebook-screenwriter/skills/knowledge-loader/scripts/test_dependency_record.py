import unittest

from dependencies import DependencyRecord, parse_dependency_record, render_dependency_record


class DependencyRecordTests(unittest.TestCase):
    def test_old_record_without_scope_fields_is_readable(self):
        record = DependencyRecord(
            artifact_id="artifact-1",
            artifact_type="script",
            built_at="2026-10-09T00:00:00Z",
            evidence=({"key": "s/p/worldview", "doc_token": "doc-1", "revision_id": 1,
                       "source_revisions": {"node": "r1"}},),
        )
        text = render_dependency_record(record)
        parsed = parse_dependency_record(text)
        self.assertEqual(parsed.artifact_id, "artifact-1")
        self.assertEqual(parsed.scope_chain, ())
        self.assertEqual(parsed.knowledge_schema, "v1")

    def test_new_record_keeps_scope_fields(self):
        record = DependencyRecord(
            artifact_id="artifact-1",
            artifact_type="script",
            built_at="2026-10-09T00:00:00Z",
            evidence=({"key": "s/p/worldview", "doc_token": "doc-1", "revision_id": 1,
                       "source_revisions": {"node": "r1"}},),
            scope_chain=({"scope_type": "project", "scope_id": "p", "authority": "system"},),
            knowledge_schema="v2",
        )
        text = render_dependency_record(record)
        parsed = parse_dependency_record(text)
        self.assertEqual(parsed.scope_chain, record.scope_chain)
        self.assertEqual(parsed.knowledge_schema, "v2")


if __name__ == "__main__":
    unittest.main()
