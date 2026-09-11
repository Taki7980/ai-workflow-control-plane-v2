import unittest

from ai_workflow.benchmark_spans import span_retrieval_metrics
from ai_workflow.models import ContextItem


class BenchmarkSpanTests(unittest.TestCase):
    def test_repository_qualified_span_metrics_measure_line_overlap(self):
        items = [
            ContextItem(
                "source",
                "backend/auth.py:10: def login():",
                metadata={
                    "path": "backend/auth.py",
                    "start_line": 10,
                    "end_line": 20,
                    "repository_id": "backend",
                },
            ),
            ContextItem(
                "source",
                "backend/auth.py:30: def refresh():",
                metadata={
                    "path": "backend/auth.py",
                    "start_line": 30,
                    "end_line": 40,
                    "repository_id": "backend",
                },
            ),
        ]
        gold = [
            {
                "repository_id": "backend",
                "path": "backend/auth.py",
                "start_line": 15,
                "end_line": 35,
            }
        ]

        metrics = span_retrieval_metrics(items, gold, k=2)

        self.assertEqual(metrics["span_recall_at_k"], 1.0)
        self.assertEqual(metrics["span_precision_at_k"], 1.0)
        self.assertEqual(metrics["first_gold_rank"], 1)
        self.assertEqual(metrics["covered_gold_lines"], 12)
        self.assertEqual(metrics["total_gold_lines"], 21)
        self.assertAlmostEqual(metrics["line_recall"], 12 / 21)

    def test_repository_identity_prevents_cross_repo_false_hit(self):
        items = [
            ContextItem(
                "source",
                "src/auth.py:10: def login():",
                metadata={
                    "path": "src/auth.py",
                    "start_line": 10,
                    "end_line": 20,
                    "repository_id": "frontend",
                },
            )
        ]
        gold = [
            {
                "repository_id": "backend",
                "path": "src/auth.py",
                "start_line": 10,
                "end_line": 20,
            }
        ]

        metrics = span_retrieval_metrics(items, gold, k=1)

        self.assertEqual(metrics["span_recall_at_k"], 0.0)
        self.assertEqual(metrics["line_recall"], 0.0)

    def test_line_budget_truncates_scored_retrieval(self):
        items = [
            ContextItem(
                "source",
                "src/service.py:1: code",
                metadata={
                    "path": "src/service.py",
                    "start_line": 1,
                    "end_line": 100,
                },
            )
        ]
        gold = [
            {
                "path": "src/service.py",
                "start_line": 40,
                "end_line": 50,
            }
        ]

        metrics = span_retrieval_metrics(
            items,
            gold,
            k=5,
            line_budget=20,
        )

        self.assertEqual(metrics["retrieved_lines"], 20)
        self.assertEqual(metrics["line_recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
