import unittest

from ai_workflow.benchmark import retrieval_metrics
from ai_workflow.models import ContextItem


class RetrievalMetricTests(unittest.TestCase):
    def test_metrics_reward_relevant_items_and_rank(self):
        items = [
            ContextItem("index", "unrelated routing prose"),
            ContextItem("source", "def ProcessPayment(): pass"),
            ContextItem("source", "class PaymentGateway: pass"),
        ]

        metrics = retrieval_metrics(
            items,
            ["processpayment", "paymentgateway"],
            k=3,
        )

        self.assertEqual(metrics["relevant_items"], 2)
        self.assertAlmostEqual(metrics["precision_at_k"], 2 / 3)
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertGreater(metrics["ndcg_at_k"], 0.0)
        self.assertLess(metrics["ndcg_at_k"], 1.0)

    def test_ndcg_is_bounded_when_multiple_items_match_one_pattern(self):
        items = [
            ContextItem("index", "test_hash_invalidation definition"),
            ContextItem("source", "test_hash_invalidation body"),
        ]

        metrics = retrieval_metrics(items, ["test_hash_invalidation"], k=5)

        self.assertLessEqual(metrics["ndcg_at_k"], 1.0)

    def test_ndcg_penalizes_gold_evidence_below_cutoff(self):
        items = [
            ContextItem("index", "payment handler"),
            ContextItem("source", "irrelevant"),
            ContextItem("source", "auth middleware"),
        ]

        metrics = retrieval_metrics(
            items,
            ["payment handler", "auth middleware"],
            k=2,
        )

        self.assertEqual(metrics["recall_at_k"], 0.5)
        self.assertLess(metrics["ndcg_at_k"], 1.0)

    def test_unlabeled_case_returns_none(self):
        self.assertIsNone(retrieval_metrics([], [], k=5))


if __name__ == "__main__":
    unittest.main()
