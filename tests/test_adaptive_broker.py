import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.adaptive_broker import gather_detailed
from ai_workflow.budget import ContextBudget
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus


CFG = {
    "context": {
        "max_results_per_source": 6,
        "semantic": {"command": "semantic-cmd", "timeout_seconds": 2, "max_results": 6},
        "sufficiency": {"threshold": 0.72},
        "adaptive_budget": {"enabled": True, "high_sufficiency_fraction": 0.45, "medium_sufficiency_fraction": 0.7, "minimum_chars": 100},
        "telemetry": {"mode": "off"},
    }
}


class AdaptiveBrokerTests(unittest.TestCase):
    def test_semantic_query_escalates_when_base_evidence_is_weak(self):
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, confidence=0.9)
        budget = ContextBudget(1200, 400, 4800, {})
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.adaptive_broker.gather_base", return_value=[ContextItem("lightweight_index", "unrelated config", 1.0)]
        ), patch(
            "ai_workflow.adaptive_broker.semantic_context", return_value=[ContextItem("semantic", "duplicate charge retry protection", 0.95)]
        ) as semantic:
            items, diagnostics = gather_detailed(
                Path(td), "Where do we prevent duplicate charges during retries?", decision, budget, CFG,
                ProviderStatus(False, False, False, False, True),
            )
        semantic.assert_called_once()
        self.assertEqual(diagnostics["retrieval_intent"], "semantic")
        self.assertTrue(any(item.source == "semantic" for item in items))
        self.assertLessEqual(sum(len(item.text) for item in items), budget.context_chars)

    def test_structural_query_does_not_call_semantic(self):
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM, structural_context=True, confidence=0.95)
        budget = ContextBudget(6000, 1200, 24000, {})
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.adaptive_broker.gather_base", return_value=[ContextItem("code_review_graph", "callers_of ProcessPayment", 9.0)]
        ), patch("ai_workflow.adaptive_broker.semantic_context") as semantic:
            _, diagnostics = gather_detailed(
                Path(td), "What breaks if ProcessPayment changes?", decision, budget, CFG,
                ProviderStatus(False, True, False, False, True), symbol="ProcessPayment",
            )
        semantic.assert_not_called()
        self.assertEqual(diagnostics["retrieval_intent"], "structural")


if __name__ == "__main__":
    unittest.main()
