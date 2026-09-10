from __future__ import annotations

import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.workspace_budget import allocate_repository_budgets
from ai_workflow.workspace_selector import RepositoryCandidate, RepositorySelection


class WorkspaceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.parent = ContextBudget(
            estimated_tokens=1000,
            output_tokens=300,
            context_chars=4000,
            source_chars={"hot_cache": 600, "lightweight": 1200, "crg": 1600, "source_fallback": 600},
        )

    def _selection(self, index: int, score: float, *, selected: bool = True) -> RepositorySelection:
        candidate = RepositoryCandidate(
            root=Path(f"/tmp/repo-{index}"),
            repository_id=f"repo-{index}",
            repository_path=f"repo-{index}",
            remote_identity=None,
            fingerprint=f"fp-{index}",
            changed_files=(),
            is_primary=index == 0,
        )
        return RepositorySelection(candidate, score, index + 1, selected, ("index_match",))

    def test_single_repo_gets_exact_parent_budget(self):
        budgets = allocate_repository_budgets(self.parent, [self._selection(0, 3.0)])
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0].context, self.parent)
        self.assertEqual(budgets[0].ratio, 1.0)

    def test_multi_repo_rank_one_gets_at_least_half_and_global_budget_is_conserved(self):
        selections = [self._selection(0, 1.0), self._selection(1, 1.0), self._selection(2, 1.0)]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertGreaterEqual(budgets[0].context.context_chars, self.parent.context_chars // 2)
        self.assertLessEqual(sum(b.context.context_chars for b in budgets), self.parent.context_chars)
        self.assertLessEqual(sum(b.context.estimated_tokens for b in budgets), self.parent.estimated_tokens)
        for source, parent_chars in self.parent.source_chars.items():
            self.assertLessEqual(sum(b.context.source_chars[source] for b in budgets), parent_chars)

    def test_zero_or_skipped_repository_receives_no_allocation(self):
        selections = [
            self._selection(0, 4.0),
            self._selection(1, 0.0),
            self._selection(2, 2.0, selected=False),
        ]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertEqual([b.repository_id for b in budgets], ["repo-0"])

    def test_rounding_and_input_order_are_deterministic(self):
        selections = [self._selection(0, 5.0), self._selection(1, 3.0), self._selection(2, 2.0)]
        first = allocate_repository_budgets(self.parent, selections)
        second = allocate_repository_budgets(self.parent, list(reversed(selections)))
        self.assertEqual(
            [(b.repository_id, b.context.context_chars, b.context.source_chars) for b in first],
            [(b.repository_id, b.context.context_chars, b.context.source_chars) for b in second],
        )

    def test_ten_repository_fixture_cannot_multiply_parent_budget(self):
        selections = [self._selection(i, float(10 - i)) for i in range(10)]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertEqual(len(budgets), 10)
        self.assertEqual(sum(b.context.context_chars for b in budgets), self.parent.context_chars)
        for source, parent_chars in self.parent.source_chars.items():
            self.assertEqual(sum(b.context.source_chars[source] for b in budgets), parent_chars)


if __name__ == "__main__":
    unittest.main()
