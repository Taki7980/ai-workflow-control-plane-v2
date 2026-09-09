from __future__ import annotations

import asyncio
import tempfile
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

        def base(root, query, decision, budget, config, providers, symbol, endpoint, changed):
            time.sleep(0.06)
            return [ContextItem("lightweight_index", f"{root.name} evidence for {query}", 1.0)]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "one").mkdir()
            (root / "two").mkdir()
            engine = WorkflowEngine(base_gather=base)
            started = time.perf_counter()
            _, diagnostics = engine.gather_detailed(
                root,
                "payment architecture dependency flow",
                decision,
                budget,
                cfg,
                ProviderStatus(False, False, False, False, False),
            )
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.15)
        self.assertEqual(diagnostics["providers_attempted"][:3], ["base", "workspace:one", "workspace:two"])
        self.assertEqual(diagnostics["scheduler"]["max_concurrency"], 4)

    def test_semantic_and_external_retrievers_execute_concurrently_in_stable_order(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        cfg["context"]["external_retrievers"] = [
            {"name": "a", "command": "unused", "intents": ["semantic"], "timeout_seconds": 1},
            {"name": "b", "command": "unused", "intents": ["semantic"], "timeout_seconds": 1},
        ]
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, confidence=0.9)
        budget = ContextBudget(1200, 400, 4800, {})

        def base(*args, **kwargs):
            return [ContextItem("lightweight_index", "unrelated config", 0.1)]

        def semantic(root, query, config, limit):
            time.sleep(0.06)
            return ProviderResult("semantic", (ContextItem("semantic", "duplicate charge retry protection", 0.95),), 60.0)

        def external(root, query, intent, spec, limit):
            time.sleep(0.06)
            name = spec["name"]
            return ProviderResult(name, (ContextItem(f"external:{name}", f"{name} duplicate charge evidence", 0.8),), 60.0)

        with tempfile.TemporaryDirectory() as td:
            engine = WorkflowEngine(base_gather=base, semantic_provider=semantic, external_provider=external)
            started = time.perf_counter()
            items, diagnostics = engine.gather_detailed(
                Path(td),
                "Where do we prevent duplicate charges during retries?",
                decision,
                budget,
                cfg,
                ProviderStatus(False, False, False, False, True),
            )
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.15)
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


if __name__ == "__main__":
    unittest.main()
