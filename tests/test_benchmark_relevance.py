import json
import unittest

from ai_workflow.benchmark_relevance import role_aware_file_metrics
from ai_workflow.models import ContextItem


def item(path: str) -> ContextItem:
    return ContextItem(
        "semantic",
        json.dumps({"file": path}),
    )


class BenchmarkRelevanceTests(unittest.TestCase):
    def test_role_metrics_separate_edit_and_support_recall(self):
        metrics = role_aware_file_metrics(
            [
                item("src/helper.py"),
                item("src/handler.py"),
                item("tests/test_handler.py"),
            ],
            [
                {"path": "src/handler.py", "role": "edit_target"},
                {
                    "path": "tests/test_handler.py",
                    "role": "supporting_context",
                },
            ],
            ["src/helper.py"],
            k=3,
        )

        self.assertEqual(metrics["edit_target_recall_at_k"], 1.0)
        self.assertEqual(metrics["supporting_context_recall_at_k"], 1.0)
        self.assertEqual(metrics["edit_target_mrr"], 0.5)
        self.assertAlmostEqual(
            metrics["known_distractor_rate_at_k"],
            1 / 3,
        )
        self.assertEqual(metrics["coverage_balance"], 1.0)
        self.assertGreater(metrics["graded_ndcg_at_k"], 0.0)
        self.assertLess(metrics["graded_ndcg_at_k"], 1.0)

    def test_graded_ndcg_rewards_edit_target_above_support(self):
        labels = [
            {"path": "src/edit.py", "role": "edit_target"},
            {"path": "src/support.py", "role": "supporting_context"},
        ]

        edit_first = role_aware_file_metrics(
            [item("src/edit.py"), item("src/support.py")],
            labels,
            [],
            k=2,
        )
        support_first = role_aware_file_metrics(
            [item("src/support.py"), item("src/edit.py")],
            labels,
            [],
            k=2,
        )

        self.assertEqual(edit_first["graded_ndcg_at_k"], 1.0)
        self.assertLess(
            support_first["graded_ndcg_at_k"],
            edit_first["graded_ndcg_at_k"],
        )

    def test_missing_support_is_visible_even_when_edit_is_found(self):
        metrics = role_aware_file_metrics(
            [item("src/edit.py"), item("src/noise.py")],
            [
                {"path": "src/edit.py", "role": "edit_target"},
                {
                    "path": "docs/design.md",
                    "role": "supporting_context",
                },
            ],
            ["src/noise.py"],
            k=2,
        )

        self.assertEqual(metrics["edit_target_recall_at_k"], 1.0)
        self.assertEqual(metrics["supporting_context_recall_at_k"], 0.0)
        self.assertEqual(metrics["coverage_balance"], 0.0)
        self.assertEqual(metrics["known_distractor_rate_at_k"], 0.5)

    def test_distractor_only_case_can_report_avoidance(self):
        metrics = role_aware_file_metrics(
            [item("src/safe.py"), item("src/decoy.py")],
            [],
            ["src/decoy.py"],
            k=2,
        )

        self.assertIsNone(metrics["weighted_recall_at_k"])
        self.assertEqual(metrics["known_distractor_rate_at_k"], 0.5)

    def test_unlabeled_case_returns_none(self):
        self.assertIsNone(role_aware_file_metrics([], [], [], k=5))


if __name__ == "__main__":
    unittest.main()
