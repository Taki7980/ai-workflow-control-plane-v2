import json
import unittest

from ai_workflow.context_economics import (
    benchmark_token_economics,
    retrieval_token_funnel,
)
from ai_workflow.models import ContextItem


def item(path: str, text: str, *, source: str = "semantic") -> ContextItem:
    return ContextItem(
        source,
        text,
        metadata={"file": path},
    )


class ContextEconomicsTests(unittest.TestCase):
    def test_token_funnel_accounts_for_duplicates_and_selection(self):
        duplicate = item("src/a.py", "a" * 40)
        retrieved = [
            duplicate,
            ContextItem(
                duplicate.source,
                duplicate.text,
                metadata=dict(duplicate.metadata),
            ),
            item("src/b.py", "b" * 80),
        ]
        ranked = [retrieved[0], retrieved[2]]
        selected = [retrieved[0]]

        metrics = retrieval_token_funnel(
            retrieved,
            ranked,
            selected,
            hard_budget_tokens=100,
            adaptive_budget_tokens=50,
            retrieval_call_count=3,
        )

        self.assertEqual(metrics["retrieved_item_count"], 3)
        self.assertEqual(metrics["unique_retrieved_item_count"], 2)
        self.assertEqual(metrics["duplicate_item_count"], 1)
        self.assertGreater(metrics["duplicate_estimated_tokens"], 0)
        self.assertEqual(metrics["selected_item_count"], 1)
        self.assertEqual(metrics["retrieval_call_count"], 3)
        self.assertLess(
            metrics["selected_vs_retrieved_token_ratio"],
            1.0,
        )
        self.assertGreater(
            metrics["estimated_token_reduction_vs_retrieved"],
            0.0,
        )

    def test_benchmark_token_economics_separates_gold_roles_and_distractors(self):
        selected = [
            item("src/edit.py", "edit " * 20),
            item("tests/test_edit.py", "support " * 10),
            item("src/legacy.py", "legacy " * 8),
            ContextItem("semantic", json.dumps({"symbol": "unknown"})),
        ]
        funnel = retrieval_token_funnel(
            selected,
            selected,
            selected,
            hard_budget_tokens=500,
            adaptive_budget_tokens=300,
            retrieval_call_count=2,
        )
        case = {
            "gold_files": ["src/edit.py", "tests/test_edit.py"],
            "file_relevance": [
                {"path": "src/edit.py", "role": "edit_target"},
                {
                    "path": "tests/test_edit.py",
                    "role": "supporting_context",
                },
            ],
            "distractor_files": ["src/legacy.py"],
        }

        metrics = benchmark_token_economics(
            selected,
            case,
            {
                "token_funnel": funnel,
                "scheduler": {"elapsed_ms": 12.5},
            },
        )

        self.assertGreater(
            metrics["selected_gold_file_estimated_tokens"],
            0,
        )
        self.assertGreater(
            metrics["selected_edit_target_estimated_tokens"],
            0,
        )
        self.assertGreater(
            metrics["selected_supporting_context_estimated_tokens"],
            0,
        )
        self.assertGreater(
            metrics["selected_known_distractor_estimated_tokens"],
            0,
        )
        self.assertGreater(metrics["gold_file_token_share"], 0.0)
        self.assertGreater(metrics["known_distractor_token_share"], 0.0)
        self.assertEqual(metrics["latency_ms"], 12.5)

    def test_empty_retrieval_does_not_invent_savings(self):
        metrics = retrieval_token_funnel(
            [],
            [],
            [],
            hard_budget_tokens=100,
            adaptive_budget_tokens=50,
            retrieval_call_count=0,
        )

        self.assertIsNone(metrics["duplicate_token_fraction"])
        self.assertIsNone(
            metrics["estimated_token_reduction_vs_retrieved"]
        )
        self.assertEqual(metrics["selected_estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
