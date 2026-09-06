import unittest

from ai_workflow.models import ContextItem


class ContextSelectionTests(unittest.TestCase):
    def test_tight_budget_prefers_highest_relevance(self):
        from ai_workflow.context_selection import select_context
        items = [
            ContextItem('a', 'payment duplicate guard', 9.0),
            ContextItem('b', 'payment logging helper', 5.0),
            ContextItem('c', 'unrelated cache text', 1.0),
        ]
        selected, diagnostics = select_context(
            'prevent duplicate payment', items, 26,
            {'context': {'selector': {'tight_budget_fraction': 0.5}}},
        )
        self.assertEqual(selected[0].source, 'a')
        self.assertEqual(diagnostics['mode'], 'relevance')
        self.assertLessEqual(sum(len(i.text) for i in selected), 26)

    def test_normal_budget_diversifies_coverage(self):
        from ai_workflow.context_selection import select_context
        items = [
            ContextItem('a', 'payment charge retry duplicate guard', 10.0),
            ContextItem('b', 'payment charge retry duplicate guard helper', 9.0),
            ContextItem('c', 'invoice idempotency persistence key', 7.0),
        ]
        selected, diagnostics = select_context(
            'payment duplicate idempotency', items, 100,
            {'context': {'selector': {'tight_budget_fraction': 0.1}}},
        )
        self.assertEqual(diagnostics['mode'], 'facility_location')
        self.assertIn('c', [i.source for i in selected])

    def test_mandatory_source_is_kept(self):
        from ai_workflow.context_selection import select_context
        items = [
            ContextItem('code_review_graph', 'impact radius evidence', 1.0),
            ContextItem('lexical', 'high score item', 100.0),
        ]
        selected, _ = select_context(
            'impact', items, 60,
            {'context': {'selector': {'tight_budget_fraction': 0.1}}},
            mandatory_sources=('code_review_graph',),
        )
        self.assertEqual(selected[0].source, 'code_review_graph')

    def test_selection_is_deterministic_and_deduped(self):
        from ai_workflow.context_selection import select_context
        items = [ContextItem('a', 'same text', 2.0), ContextItem('b', 'same text', 1.0)]
        config = {'context': {'selector': {'tight_budget_fraction': 0.1}}}
        first, _ = select_context('same', items, 100, config)
        second, _ = select_context('same', items, 100, config)
        self.assertEqual([i.source for i in first], [i.source for i in second])
        self.assertEqual(len(first), 1)


if __name__ == '__main__':
    unittest.main()
