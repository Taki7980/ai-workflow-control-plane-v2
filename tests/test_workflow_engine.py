from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.retrieval_contracts import ProviderResult


class WorkflowEngineTests(unittest.TestCase):
    def _config(self) -> dict:
        cfg = default_config()
        cfg["execution"]["retrieval_scheduler"] = {"max_concurrency": 4, "global_deadline_seconds": 1.0}
        cfg["context"]["sufficiency"]["threshold"] = 0.95
        return cfg

    def test_workspace_roots_execute_concurrently_but_diagnostics_keep_root_order(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        cfg["workspace"]["roots"] = ["one", "two"]
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM, confidence=0.9)
        budget = ContextBudget(6000, 1200, 24000, {})
        lock = threading.Lock()
        active = 0
        max_active = 0

        def base(root, query, decision, budget, config, providers, symbol, endpoint, changed):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.06)
                return [ContextItem("lightweight_index", f"{root.name} evidence for {query}", 1.0)]
            finally:
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "one").mkdir()
            (root / "two").mkdir()
            engine = WorkflowEngine(base_gather=base)
            _, diagnostics = engine.gather_detailed(
                root,
                "payment architecture dependency flow",
                decision,
                budget,
                cfg,
                ProviderStatus(False, False, False, False, False),
            )

        self.assertGreaterEqual(max_active, 2)
        self.assertEqual(diagnostics["providers_attempted"][:3], ["base", "workspace:one", "workspace:two"])
        self.assertEqual(diagnostics["scheduler"]["max_concurrency"], 4)

    def test_semantic_and_external_retrievers_execute_concurrently_in_stable_order(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        cfg["context"]["external_retrievers"] = [
            {"name": "a", "provider_id": "a-v1", "intents": ["semantic"], "timeout_seconds": 1},
            {"name": "b", "provider_id": "b-v1", "intents": ["semantic"], "timeout_seconds": 1},
        ]
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, confidence=0.9)
        budget = ContextBudget(1200, 400, 4800, {})
        lock = threading.Lock()
        active = 0
        max_active = 0

        def base(*args, **kwargs):
            return [ContextItem("lightweight_index", "unrelated config", 0.1)]

        def enter_provider() -> None:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)

        def leave_provider() -> None:
            nonlocal active
            with lock:
                active -= 1

        def semantic(root, query, config, limit):
            enter_provider()
            try:
                time.sleep(0.06)
                return ProviderResult("semantic", (ContextItem("semantic", "duplicate charge retry protection", 0.95),), 60.0)
            finally:
                leave_provider()

        def external(root, query, intent, spec, limit):
            enter_provider()
            try:
                time.sleep(0.06)
                name = spec["name"]
                return ProviderResult(name, (ContextItem(f"external:{name}", f"{name} duplicate charge evidence", 0.8),), 60.0)
            finally:
                leave_provider()

        with tempfile.TemporaryDirectory() as td:
            engine = WorkflowEngine(base_gather=base, semantic_provider=semantic, external_provider=external)
            items, diagnostics = engine.gather_detailed(
                Path(td),
                "Where do we prevent duplicate charges during retries?",
                decision,
                budget,
                cfg,
                ProviderStatus(False, False, False, False, True),
            )

        self.assertGreaterEqual(max_active, 2)
        self.assertEqual(diagnostics["providers_attempted"], ["base", "semantic", "external:a", "external:b"])
        self.assertEqual(diagnostics["provider_errors"], {})
        self.assertTrue(any(item.source == "semantic" for item in items))

    def test_async_api_uses_same_engine_contract(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, confidence=0.9)
        budget = ContextBudget(1200, 400, 4800, {})
        engine = WorkflowEngine(base_gather=lambda *args, **kwargs: [ContextItem("lightweight_index", "answer evidence", 3.0)])

        with tempfile.TemporaryDirectory() as td:
            items, diagnostics = asyncio.run(
                engine.gather_detailed_async(
                    Path(td), "answer evidence", decision, budget, cfg,
                    ProviderStatus(False, False, False, False, False),
                )
            )
        self.assertTrue(items)
        self.assertIn("scheduler", diagnostics)


    def test_structural_mixed_query_uses_semantic_anchor_then_graph_expansion(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        cfg["context"]["sufficiency"]["threshold"] = 0.4
        decision = RouteDecision(
            Lane.FULL,
            Risk.MEDIUM,
            structural_context=True,
            confidence=0.9,
        )
        budget = ContextBudget(6000, 1200, 24000, {})
        structural_calls = []

        def base(*args, **kwargs):
            return [
                ContextItem(
                    "lightweight_index",
                    "payment retry handler",
                    0.4,
                )
            ]

        def semantic(root, query, config, limit):
            return ProviderResult(
                "semantic",
                (
                    ContextItem(
                        "semantic",
                        "billing.py:10 payment retry handler",
                        0.95,
                        False,
                        {
                            "path": "billing.py",
                            "symbol": "ProcessPayment",
                        },
                    ),
                ),
            )

        def structural(
            root,
            query,
            symbol,
            changed_files,
            limit,
            *,
            patterns=(),
        ):
            structural_calls.append(
                {
                    "symbol": symbol,
                    "changed_files": list(changed_files or []),
                    "patterns": tuple(patterns),
                }
            )
            return [
                ContextItem(
                    "code_review_graph",
                    "billing.py impacts checkout.py through ProcessPayment",
                    9.0,
                    False,
                    {
                        "pattern": "impact",
                        "structural_valid": True,
                        "result_count": 1,
                    },
                )
            ]

        with tempfile.TemporaryDirectory() as td:
            engine = WorkflowEngine(
                base_gather=base,
                semantic_provider=semantic,
                structural_provider=structural,
            )
            items, diagnostics = engine.gather_detailed(
                Path(td),
                "What breaks if the payment retry handler changes?",
                decision,
                budget,
                cfg,
                ProviderStatus(False, True, False, False, True),
            )

        self.assertEqual(diagnostics["retrieval_intent"], "mixed")
        self.assertIn("semantic", diagnostics["providers_attempted"])
        self.assertIn(
            "structural-expansion",
            diagnostics["providers_attempted"],
        )
        self.assertEqual(len(structural_calls), 1)
        self.assertEqual(
            structural_calls[0],
            {
                "symbol": "ProcessPayment",
                "changed_files": ["billing.py"],
                "patterns": ("impact",),
            },
        )
        self.assertTrue(diagnostics["sufficiency"]["structural_complete"])
        self.assertTrue(
            any(item.source == "code_review_graph" for item in items)
        )


    def test_explicit_symbol_wins_over_semantic_anchor(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        decision = RouteDecision(
            Lane.FULL,
            Risk.MEDIUM,
            structural_context=True,
            confidence=0.9,
        )
        budget = ContextBudget(6000, 1200, 24000, {})
        seen = []

        def base(*args, **kwargs):
            return [ContextItem("lightweight_index", "payment evidence", 0.1)]

        def semantic(root, query, config, limit):
            return ProviderResult(
                "semantic",
                (
                    ContextItem(
                        "semantic",
                        "wrong.py:1 guessed handler",
                        0.95,
                        False,
                        {"path": "wrong.py", "symbol": "WrongAnchor"},
                    ),
                ),
            )

        def structural(
            root,
            query,
            symbol,
            changed_files,
            limit,
            *,
            patterns=(),
        ):
            seen.append(symbol)
            return [
                ContextItem(
                    "code_review_graph",
                    "Caller -> ProcessPayment",
                    9.0,
                    False,
                    {
                        "pattern": "callers_of",
                        "structural_valid": True,
                        "result_count": 1,
                    },
                )
            ]

        with tempfile.TemporaryDirectory() as td:
            engine = WorkflowEngine(
                base_gather=base,
                semantic_provider=semantic,
                structural_provider=structural,
            )
            engine.gather_detailed(
                Path(td),
                "Who calls ProcessPayment?",
                decision,
                budget,
                cfg,
                ProviderStatus(False, True, False, False, True),
                symbol="ProcessPayment",
            )

        self.assertEqual(seen, ["ProcessPayment"])


if __name__ == "__main__":
    unittest.main()
