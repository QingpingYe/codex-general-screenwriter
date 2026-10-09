import unittest

from scope_model import ScopeChainNode, ScopeRef, expand_scope_chain, scope_matches


class ScopeModelTests(unittest.TestCase):
    def test_task_to_global_chain_expands_in_order(self):
        scope = ScopeRef(
            task_id="task-1",
            scene_id="scene-1",
            episode_id="ep-1",
            season_id="season-1",
            project_id="project-1",
            series_id="series-1",
            genre_ids=("mystery",),
            medium_id="picturebook",
            authority="system",
        )
        chain = expand_scope_chain(scope)
        self.assertEqual(
            [node.scope_type for node in chain],
            ["task", "scene", "episode", "season", "project", "series", "genre", "medium", "global"],
        )
        self.assertEqual(chain[0].scope_id, "task-1")
        self.assertEqual(chain[-1].scope_type, "global")

    def test_absent_levels_are_skipped(self):
        scope = ScopeRef(project_id="project-1", medium_id="film")
        chain = expand_scope_chain(scope)
        self.assertEqual([node.scope_type for node in chain], ["project", "medium", "global"])

    def test_multiple_genre_entries_are_individually_matched(self):
        scope = ScopeRef(genre_ids=("mystery", "comedy"), medium_id="film")
        chain = expand_scope_chain(scope)
        self.assertEqual(
            [node.scope_id for node in chain if node.scope_type == "genre"],
            ["mystery", "comedy"],
        )

    def test_matching_by_scope_type_and_id(self):
        scope = ScopeRef(project_id="project-1", medium_id="film")
        chain = expand_scope_chain(scope)
        self.assertTrue(scope_matches(chain, ScopeChainNode("project", "project-1")))
        self.assertFalse(scope_matches(chain, ScopeChainNode("project", "project-2")))
        self.assertFalse(scope_matches(chain, ScopeChainNode("series", "project-1")))

    def test_rejects_empty_scope(self):
        with self.assertRaises(ValueError):
            expand_scope_chain(ScopeRef())

    def test_rejects_unknown_scope_type(self):
        with self.assertRaises(ValueError):
            ScopeChainNode("unknown", "x")


if __name__ == "__main__":
    unittest.main()
