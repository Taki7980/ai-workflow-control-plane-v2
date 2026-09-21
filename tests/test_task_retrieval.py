from __future__ import annotations

import unittest

from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.retrieval_policy import classify_retrieval_intent
from ai_workflow.task_retrieval import task_retrieval_policy


class TaskRetrievalPolicyTests(unittest.TestCase):
    def _policy(self, query: str, *, changed: list[str] | None = None):
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM)
        plan = classify_retrieval_intent(query, decision)
        return task_retrieval_policy(query, plan, changed_files=changed)

    def test_failure_trace_prioritizes_lexical_anchors(self):
        policy = self._policy("Traceback TypeError in ProcessPayment at billing.py:41")
        self.assertEqual(policy.profile, "trace2code")
        self.assertGreater(policy.lexical_weight, policy.specialist_weight)

    def test_test_discovery_prioritizes_specialist_and_lexical_evidence(self):
        policy = self._policy("Which tests cover ProcessPayment after this change?")
        self.assertEqual(policy.profile, "code2test")
        self.assertGreater(policy.specialist_weight, policy.source_weight)
        self.assertGreater(policy.lexical_weight, policy.source_weight)

    def test_change_impact_prioritizes_structural_specialists(self):
        policy = self._policy(
            "What is the blast radius of this change?",
            changed=["billing.py"],
        )
        self.assertEqual(policy.profile, "edit2ripple")
        self.assertGreater(policy.specialist_weight, policy.lexical_weight)

    def test_review_comment_prefers_semantic_context(self):
        policy = self._policy("Address the review comment about retry ownership")
        self.assertEqual(policy.profile, "comment2context")
        self.assertGreater(policy.specialist_weight, policy.lexical_weight)

    def test_exact_identifier_keeps_lexical_priority(self):
        policy = self._policy("Where is ProcessPayment?")
        self.assertEqual(policy.profile, "exact")
        self.assertGreater(policy.lexical_weight, policy.specialist_weight)

    def test_policy_is_deterministic(self):
        query = "Traceback in CheckoutService while processing payment"
        first = self._policy(query)
        second = self._policy(query)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
