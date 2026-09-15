import unittest

from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.retrieval_policy import (
    RetrievalIntent,
    classify_retrieval_intent,
    evaluate_sufficiency,
    structural_requirements,
)


class RetrievalPolicyTests(unittest.TestCase):
    def test_exact_identifier_query(self):
        decision = RouteDecision(Lane.ANSWER, Risk.LOW)
        plan = classify_retrieval_intent(
            "Where is ProcessPayment?",
            decision,
            symbol="ProcessPayment",
        )
        self.assertEqual(plan.intent, RetrievalIntent.EXACT)
        self.assertTrue(plan.use_lexical)
        self.assertFalse(plan.use_semantic)

    def test_semantic_paraphrase_query(self):
        decision = RouteDecision(Lane.ANSWER, Risk.LOW)
        plan = classify_retrieval_intent(
            "Where do we prevent duplicate customer charges during retries?",
            decision,
        )
        self.assertEqual(plan.intent, RetrievalIntent.SEMANTIC)
        self.assertTrue(plan.use_semantic)

    def test_structural_query_with_exact_anchor_skips_semantic(self):
        decision = RouteDecision(
            Lane.FULL,
            Risk.MEDIUM,
            structural_context=True,
        )
        plan = classify_retrieval_intent(
            "Who calls ProcessPayment?",
            decision,
            symbol="ProcessPayment",
        )
        self.assertEqual(plan.intent, RetrievalIntent.STRUCTURAL)
        self.assertTrue(plan.use_structural)
        self.assertFalse(plan.use_semantic)
        self.assertEqual(plan.structural_patterns, ("callers_of",))

    def test_structural_query_without_exact_anchor_is_mixed(self):
        decision = RouteDecision(
            Lane.FULL,
            Risk.MEDIUM,
            structural_context=True,
        )
        plan = classify_retrieval_intent(
            "What breaks if the payment retry handler changes?",
            decision,
        )
        self.assertEqual(plan.intent, RetrievalIntent.MIXED)
        self.assertTrue(plan.use_structural)
        self.assertTrue(plan.use_semantic)
        self.assertEqual(plan.structural_patterns, ("impact",))

    def test_structural_requirements_are_query_aware(self):
        self.assertEqual(
            structural_requirements("Who calls ProcessPayment?"),
            ("callers_of",),
        )
        self.assertEqual(
            structural_requirements("What does ProcessPayment call?"),
            ("callees_of",),
        )
        self.assertEqual(
            structural_requirements("Which tests cover ProcessPayment?"),
            ("tests_for",),
        )
        self.assertEqual(
            structural_requirements("What is the blast radius of this change?"),
            ("impact",),
        )
        self.assertEqual(
            structural_requirements(
                "What callers depend on ProcessPayment?"
            ),
            ("callers_of",),
        )

    def test_sufficiency_is_bounded_and_requires_structural_evidence(self):
        items = [
            ContextItem(
                "lightweight_index",
                "ProcessPayment payment retry handler",
                10.0,
            )
        ]
        normal = evaluate_sufficiency(
            "ProcessPayment payment retry",
            items,
            threshold=0.5,
        )
        structural = evaluate_sufficiency(
            "ProcessPayment payment retry",
            items,
            structural_required=True,
            structural_patterns=("callers_of",),
            threshold=0.5,
        )
        self.assertGreaterEqual(normal.score, 0.0)
        self.assertLessEqual(normal.score, 1.0)
        self.assertTrue(normal.sufficient)
        self.assertFalse(structural.sufficient)

    def test_unrelated_crg_search_hit_is_not_structural_completion(self):
        items = [
            ContextItem(
                "code_review_graph",
                '{"status":"ok","results":[{"name":"ProcessPayment"}]}',
                5.0,
                False,
                {
                    "pattern": "search",
                    "structural_valid": False,
                    "result_count": 1,
                },
            )
        ]
        result = evaluate_sufficiency(
            "Who calls ProcessPayment?",
            items,
            structural_required=True,
            structural_patterns=("callers_of",),
            threshold=0.1,
        )
        self.assertFalse(result.structural_complete)
        self.assertFalse(result.sufficient)

    def test_matching_crg_relation_can_complete_structural_requirement(self):
        items = [
            ContextItem(
                "code_review_graph",
                "ProcessPayment is called by CheckoutService",
                9.0,
                False,
                {
                    "pattern": "callers_of",
                    "structural_valid": True,
                    "result_count": 1,
                },
            )
        ]
        result = evaluate_sufficiency(
            "Who calls ProcessPayment?",
            items,
            structural_required=True,
            structural_patterns=("callers_of",),
            threshold=0.1,
        )
        self.assertTrue(result.structural_complete)
        self.assertTrue(result.sufficient)

    def test_verified_empty_relation_is_structurally_complete(self):
        items = [
            ContextItem(
                "code_review_graph",
                "No callers found; graph is current.",
                9.0,
                False,
                {
                    "pattern": "callers_of",
                    "structural_valid": True,
                    "empty_verified": True,
                    "result_count": 0,
                },
            )
        ]
        result = evaluate_sufficiency(
            "Who calls ProcessPayment?",
            items,
            structural_required=True,
            structural_patterns=("callers_of",),
            threshold=0.1,
        )
        self.assertTrue(result.structural_complete)


if __name__ == "__main__":
    unittest.main()
