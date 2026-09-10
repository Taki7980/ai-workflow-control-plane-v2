import unittest

from ai_workflow.models import ContextItem
from ai_workflow.workflow_engine import _algorithm_policy, _hybrid_rank


class WorkflowAlgorithmControlTests(unittest.TestCase):
    def test_adaptive_without_specialists_preserves_base_order(self):
        items = [
            ContextItem("base", "first context", score=0.1),
            ContextItem("base", "second context", score=0.9),
        ]

        ranked = _hybrid_rank(
            "second",
            items,
            [],
            1,
            {},
        )

        self.assertEqual([item.text for item in ranked], [
            "first context",
            "second context",
        ])

    def test_source_profile_ranks_by_provider_score(self):
        items = [
            ContextItem("base", "alpha", score=0.2),
            ContextItem("base", "beta", score=0.9),
        ]
        config = {
            "context": {
                "experiments": {"hybrid_ranker": "source"},
            }
        }

        ranked = _hybrid_rank("alpha", items, [], 2, config)

        self.assertEqual([item.text for item in ranked], ["beta", "alpha"])

    def test_bm25_profile_prioritizes_lexical_match(self):
        items = [
            ContextItem("base", "payment reconciliation service", score=0.1),
            ContextItem("base", "generic helper utilities", score=1.0),
        ]
        config = {
            "context": {
                "experiments": {"hybrid_ranker": "bm25"},
            }
        }

        ranked = _hybrid_rank("payment reconciliation", items, [], 2, config)

        self.assertEqual(ranked[0].text, "payment reconciliation service")

    def test_algorithm_policy_clamps_mmr_lambda_and_rrf_k(self):
        config = {
            "context": {
                "experiments": {
                    "hybrid_ranker": "rrf_mmr",
                    "mmr_lambda": 4,
                    "rrf_k": 0,
                    "disable_early_sufficiency_gate": True,
                }
            }
        }

        policy = _algorithm_policy(config)

        self.assertEqual(policy["hybrid_ranker"], "rrf_mmr")
        self.assertEqual(policy["mmr_lambda"], 1.0)
        self.assertEqual(policy["rrf_k"], 1)
        self.assertTrue(policy["disable_early_sufficiency_gate"])


if __name__ == "__main__":
    unittest.main()
