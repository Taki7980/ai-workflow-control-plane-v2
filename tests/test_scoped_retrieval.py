from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.context_broker import lightweight
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.workflow_engine import WorkflowEngine


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ScopedRetrievalTests(unittest.TestCase):
    def test_lightweight_reads_central_index_but_returns_repo_local_path(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            backend = workspace / "backend"
            frontend = workspace / "frontend"
            backend.mkdir()
            frontend.mkdir()
            backend_file = backend / "payments.py"
            frontend_file = frontend / "payment.ts"
            backend_file.write_text("def ProcessPayment():\n    return True\n", encoding="utf-8")
            frontend_file.write_text("export function PaymentForm() {}\n", encoding="utf-8")
            generated = workspace / "ai-workspace" / "generated"
            generated.mkdir(parents=True)
            backend_sha = _sha(backend_file)
            frontend_sha = _sha(frontend_file)
            (generated / "index-state.json").write_text(
                json.dumps({
                    "version": 2,
                    "files": {
                        "backend/payments.py": {"sha256": backend_sha},
                        "frontend/payment.ts": {"sha256": frontend_sha},
                    },
                }),
                encoding="utf-8",
            )
            (generated / "symbol-index.jsonl").write_text(
                "\n".join([
                    json.dumps({"symbol": "ProcessPayment", "file": "backend/payments.py", "line": 1, "sha256": backend_sha}),
                    json.dumps({"symbol": "PaymentForm", "file": "frontend/payment.ts", "line": 1, "sha256": frontend_sha}),
                ]) + "\n",
                encoding="utf-8",
            )
            (generated / "endpoint-index.jsonl").write_text("", encoding="utf-8")

            items = lightweight(
                backend,
                "ProcessPayment",
                "ProcessPayment",
                None,
                6,
                0.5,
                workspace_root=workspace,
                repository_path="backend",
            )

            texts = "\n".join(item.text for item in items)
            self.assertIn("ProcessPayment", texts)
            self.assertNotIn("PaymentForm", texts)
            self.assertIn('"file":"payments.py"', texts)
            self.assertNotIn('"file":"backend/payments.py"', texts)

    def test_workflow_engine_scoped_call_uses_one_repo_and_exact_slice(self):
        captured = []

        def base_gather(root, query, decision, budget, config, providers, symbol, endpoint, changed, **kwargs):
            captured.append((Path(root), budget.context_chars, tuple(changed), kwargs))
            return [ContextItem("targeted_source", "payments.py:1 ProcessPayment", 1.0)]

        config = default_config()
        providers = ProviderStatus(False, False, False, False, False)
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
        budget = ContextBudget(100, 20, 1200, {"hot_cache": 100, "lightweight": 300, "crg": 400, "source_fallback": 400})

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            repo = workspace / "backend"
            repo.mkdir()
            engine = WorkflowEngine(base_gather=base_gather)
            items, diagnostics = engine.gather_detailed(
                repo,
                "ProcessPayment",
                decision,
                budget,
                config,
                providers,
                changed_files=["payments.py"],
                workspace_root=workspace,
                repository_path="backend",
            )

        self.assertTrue(items)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0].name, "backend")
        self.assertEqual(captured[0][1], 1200)
        self.assertEqual(captured[0][2], ("payments.py",))
        self.assertEqual(Path(captured[0][3]["workspace_root"]).name, Path(td).name)
        self.assertEqual(captured[0][3]["repository_path"], "backend")
        self.assertEqual(diagnostics["repository_path"], "backend")

    def test_unscoped_engine_preserves_legacy_base_gather_signature(self):
        calls = []

        def legacy_base(root, query, decision, budget, config, providers, symbol, endpoint, changed):
            calls.append(Path(root))
            return [ContextItem("targeted_source", "legacy.py:1 answer", 1.0)]

        config = default_config()
        providers = ProviderStatus(False, False, False, False, False)
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
        budget = ContextBudget(100, 20, 600, {"hot_cache": 50, "lightweight": 150, "crg": 200, "source_fallback": 200})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = WorkflowEngine(base_gather=legacy_base)
            items, _ = engine.gather_detailed(root, "answer", decision, budget, config, providers)
        self.assertTrue(items)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
