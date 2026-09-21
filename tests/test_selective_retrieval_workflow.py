from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.workflow_engine import WorkflowEngine


class SelectiveRetrievalWorkflowTests(unittest.TestCase):
    def _run(self, *, enabled=True):
        config = default_config()
        config["context"]["sufficiency"]["threshold"] = 0.1
        config["context"]["selective_retrieval"] = {
            "enabled": enabled,
            "minimum_coverage": 0.15,
        }
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, confidence=0.9)
        budget = ContextBudget(4000, 500, 16000, {})
        providers = ProviderStatus(False, False, False, False, False)
        engine = WorkflowEngine(
            base_gather=lambda *args, **kwargs: [
                ContextItem(
                    "targeted_source",
                    "banana unrelated module",
                    999.0,
                    False,
                    {"path": "src/unrelated.py"},
                )
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            return engine.gather_detailed(
                Path(td),
                "payment retry",
                decision,
                budget,
                config,
                providers,
            )

    def test_high_provider_score_cannot_override_selective_abstention(self):
        _, diagnostics = self._run(enabled=True)
        self.assertTrue(diagnostics["sufficiency"]["sufficient"])
        self.assertEqual(
            diagnostics["selective_retrieval"]["condition"],
            "irrelevant",
        )
        self.assertFalse(diagnostics["selective_retrieval"]["accept"])
        self.assertEqual(diagnostics["evidence_state"], "abstain")

    def test_disabled_gate_preserves_legacy_evidence_state(self):
        _, diagnostics = self._run(enabled=False)
        self.assertFalse(diagnostics["selective_retrieval"]["accept"])
        self.assertFalse(diagnostics["selective_retrieval"]["enabled"])
        self.assertEqual(diagnostics["evidence_state"], "sufficient")


if __name__ == "__main__":
    unittest.main()
