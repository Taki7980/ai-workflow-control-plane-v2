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

    def test_engine_executes_only_requested_repository_when_workspace_roots_exist(self):
        from ai_workflow.workflow_engine import WorkflowEngine

        cfg = self._config()
        cfg["workspace"]["roots"] = ["one", "two"]
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM, confidence=0.9)
        budget = ContextBudget(6000, 1200, 24000, {})
        calls = []

        def base(root, query, decision, budget, config, providers, symbol, endpoint, changed):
            calls.append(Path(root).resolve())
            return [ContextItem("lightweight_index", f"{root.name} evidence for {query}", 1.0)]

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
            expected_root = root.resolve()

        self.assertEqual(calls, [expected_root])
        self.assertEqual(diagnostics["providers_attempted"][0], "base")
        self.assertFalse(any(label.startswith("workspace:") for label in diagnostics["providers_attempted"]))
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


if __name__ == "__main__":
    unittest.main()
