import unittest

from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.retrieval_policy import RetrievalIntent, classify_retrieval_intent, evaluate_sufficiency


class RetrievalPolicyTests(unittest.TestCase):
    def test_exact_identifier_query(self):
        decision = RouteDecision(Lane.ANSWER, Risk.LOW)
        plan = classify_retrieval_intent("Where is ProcessPayment?", decision, symbol="ProcessPayment")
        self.assertEqual(plan.intent, RetrievalIntent.EXACT)
        self.assertTrue(plan.use_lexical)
        self.assertFalse(plan.use_semantic)

    def test_semantic_paraphrase_query(self):
        decision = RouteDecision(Lane.ANSWER, Risk.LOW)
        plan = classify_retrieval_intent("Where do we prevent duplicate customer charges during retries?", decision)
        self.assertEqual(plan.intent, RetrievalIntent.SEMANTIC)
        self.assertTrue(plan.use_semantic)

    def test_structural_query_skips_semantic(self):
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM, structural_context=True)
        plan = classify_retrieval_intent("What breaks if ProcessPayment changes?", decision)
        self.assertEqual(plan.intent, RetrievalIntent.STRUCTURAL)
        self.assertTrue(plan.use_structural)
        self.assertFalse(plan.use_semantic)

    def test_sufficiency_is_bounded_and_requires_structural_evidence(self):
        items = [ContextItem("lightweight_index", "ProcessPayment payment retry handler", 10.0)]
        normal = evaluate_sufficiency("ProcessPayment payment retry", items, threshold=0.5)
        structural = evaluate_sufficiency("ProcessPayment payment retry", items, structural_required=True, threshold=0.5)
        self.assertGreaterEqual(normal.score, 0.0)
        self.assertLessEqual(normal.score, 1.0)
        self.assertTrue(normal.sufficient)
        self.assertFalse(structural.sufficient)


if __name__ == "__main__":
    unittest.main()
