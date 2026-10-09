import unittest

from scope_pages import ScopeEnvelope, ScopeEnvelopeError, parse_scope_envelope


class ScopePagesTests(unittest.TestCase):
    def test_parse_valid_scope_envelope(self):
        body = """# Page

## knowledge-scope
```json
{
  "schema_version": 2,
  "scope_type": "project",
  "scope_id": "project-1",
  "authority": "system",
  "medium_id": "film",
  "genre_ids": ["mystery"],
  "version": 3,
  "depends_on": [],
  "source_refs": [],
  "built_against": {}
}
```
"""
        envelope = parse_scope_envelope(body)
        self.assertEqual(envelope.scope_type, "project")
        self.assertEqual(envelope.scope_id, "project-1")
        self.assertEqual(envelope.authority, "system")
        self.assertEqual(envelope.medium_id, "film")
        self.assertEqual(envelope.genre_ids, ("mystery",))
        self.assertEqual(envelope.version, 3)

    def test_missing_scope_envelope_returns_none(self):
        self.assertIsNone(parse_scope_envelope("# Page"))

    def test_malformed_json_raises(self):
        body = "## knowledge-scope\n```json\nnot-json\n```\n"
        with self.assertRaises(ScopeEnvelopeError):
            parse_scope_envelope(body)

    def test_unknown_field_raises(self):
        body = '## knowledge-scope\n```json\n{"schema_version":2,"scope_type":"project","scope_id":"p","authority":"system","extra":1}\n```\n'
        with self.assertRaises(ScopeEnvelopeError):
            parse_scope_envelope(body)

    def test_invalid_scope_type_raises(self):
        body = '## knowledge-scope\n```json\n{"schema_version":2,"scope_type":"bogus","scope_id":"p","authority":"system"}\n```\n'
        with self.assertRaises(ScopeEnvelopeError):
            parse_scope_envelope(body)

    def test_invalid_authority_raises(self):
        body = '## knowledge-scope\n```json\n{"schema_version":2,"scope_type":"project","scope_id":"p","authority":"bogus"}\n```\n'
        with self.assertRaises(ScopeEnvelopeError):
            parse_scope_envelope(body)


if __name__ == "__main__":
    unittest.main()
