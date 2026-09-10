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

    def test_stage3_metric_identity(self):
        from ai_workflow.benchmark import repository_metrics

        items = [
            ContextItem("source", "left evidence", metadata={"repository_path": "left/api", "file": "service.py"}),
            ContextItem("source", "right evidence", metadata={"repository_path": "right/api", "file": "service.py"}),
        ]
        first = repository_metrics(items, ["left/api"], ["right/api"], k=1)
        both = repository_metrics(items, ["left/api"], ["right/api"], k=2)
        self.assertEqual(first["repo_recall_at_k"], 1.0)
        self.assertEqual(first["wrong_repo_rate"], 0.0)
        self.assertEqual(both["wrong_repo_rate"], 0.5)

    def test_stage3_metric_files(self):
        from ai_workflow.benchmark import file_recall

        items = [
            ContextItem(
                "source",
                "payment implementation",
                metadata={"repository_path": "backend", "file": "internal/payment/service.go"},
            )
        ]
        self.assertEqual(file_recall(items, ["internal/payment/service.go"], k=5), 1.0)
        self.assertEqual(file_recall(items, ["backend/internal/payment/service.go"], k=5), 1.0)
        self.assertEqual(file_recall(items, ["service.go"], k=5), 0.0)
        self.assertIsNone(file_recall(items, [], k=5))

    def test_stage3_metric_unlabeled_repo_case(self):
        from ai_workflow.benchmark import repository_metrics

        self.assertIsNone(repository_metrics([], [], [], k=5))


    def test_stage4_graph_metrics(self):
        from ai_workflow.workspace_graph_metrics import (
            cross_repo_edge_recall,
            graph_context_yield,
            graph_node_recall_at_k,
            structural_recall_at_k,
            wrong_edge_rate,
        )

        items = [
            ContextItem(
                "workspace_graph",
                "frontend client calls payment endpoint",
                metadata={
                    "graph_node_id": "node-client",
                    "graph_edge_ids": ["edge-api"],
                },
            ),
            ContextItem(
                "workspace_graph",
                "backend payment handler",
                metadata={
                    "graph_node_id": "node-handler",
                    "graph_edge_ids": ["edge-impl"],
                },
            ),
            ContextItem(
                "workspace_graph",
                "unrelated graph evidence",
                metadata={
                    "graph_node_id": "node-noise",
                    "graph_edge_ids": ["edge-noise"],
                },
            ),
        ]

        self.assertEqual(
            graph_node_recall_at_k(
                items, ["node-client", "node-handler"], k=2
            ),
            1.0,
        )
        self.assertEqual(
            cross_repo_edge_recall(items, ["edge-api"], k=3),
            1.0,
        )
        self.assertAlmostEqual(
            wrong_edge_rate(
                items,
                ["edge-api", "edge-impl"],
                k=3,
            ),
            1 / 3,
        )
        self.assertEqual(
            structural_recall_at_k(
                items,
                ["payment endpoint", "payment handler"],
                k=2,
            ),
            1.0,
        )
        self.assertGreater(
            graph_context_yield(
                items,
                ["payment endpoint", "payment handler"],
                k=3,
            ),
            0.0,
        )

    def test_stage4_graph_metrics_return_none_without_gold(self):
        from ai_workflow.workspace_graph_metrics import (
            cross_repo_edge_recall,
            graph_context_yield,
            graph_node_recall_at_k,
            structural_recall_at_k,
            wrong_edge_rate,
        )

        self.assertIsNone(graph_node_recall_at_k([], [], k=5))
        self.assertIsNone(cross_repo_edge_recall([], [], k=5))
        self.assertIsNone(wrong_edge_rate([], [], k=5))
        self.assertIsNone(structural_recall_at_k([], [], k=5))
        self.assertIsNone(graph_context_yield([], [], k=5))


if __name__ == "__main__":
    unittest.main()
