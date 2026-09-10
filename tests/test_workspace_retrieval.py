from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.workspace_budget import RepositoryBudget
from ai_workflow.workspace_retrieval import gather_workspace_detailed_async
from ai_workflow.workspace_selector import RepositoryCandidate, RepositorySelection


class WorkspaceRetrievalTests(unittest.TestCase):
    def test_multi_repo_merge_preserves_provenance_and_parent_budget(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            a_root = workspace / "backend"
            b_root = workspace / "frontend"
            skipped_root = workspace / "docs"
            for root in (a_root, b_root, skipped_root):
                root.mkdir()

            a = RepositoryCandidate(a_root, "repo-a", "backend", "github.com/acme/backend", "fp-a", ("payments.py",), False)
            b = RepositoryCandidate(b_root, "repo-b", "frontend", "github.com/acme/frontend", "fp-b", (), False)
            c = RepositoryCandidate(skipped_root, "repo-c", "docs", "github.com/acme/docs", "fp-c", (), False)
            selections = [
                RepositorySelection(a, 20.0, 1, True, ("changed_file",)),
                RepositorySelection(b, 10.0, 2, True, ("identity_match",)),
                RepositorySelection(c, 0.0, 3, False, ("no_relevant_signal",)),
            ]
            parent = ContextBudget(300, 60, 1000, {"hot_cache": 100, "lightweight": 300, "crg": 400, "source_fallback": 200})
            budgets = [
                RepositoryBudget("repo-a", 1, 0.6, ContextBudget(180, 0, 600, {"hot_cache": 60, "lightweight": 180, "crg": 240, "source_fallback": 120})),
                RepositoryBudget("repo-b", 2, 0.4, ContextBudget(120, 0, 400, {"hot_cache": 40, "lightweight": 120, "crg": 160, "source_fallback": 80})),
            ]
            config = default_config()
            providers = ProviderStatus(False, False, False, False, False)
            decision = RouteDecision(Lane.FULL, Risk.MEDIUM, ["test"], True, 0.9)

            async def fake_gather(root, query, decision, budget, config, providers, symbol=None, endpoint=None, changed_files=None, **kwargs):
                if Path(root).name == "backend":
                    await asyncio.sleep(0.02)
                item = ContextItem("targeted_source", "shared evidence", 1.0, False, {"file": "x.py"}, {"workspace_root": "/must/not/leak"})
                return [item], {"retrieval_intent": "mixed", "evidence_state": "sufficient", "sufficiency": {"sufficient": True, "score": 1.0}, "fallbacks": [], "orchestration": {"complexity_score": 1}}

            with patch("ai_workflow.workspace_retrieval.build_repository_candidates", return_value=[a, b, c]), \
                 patch("ai_workflow.workspace_retrieval.select_repositories", return_value=selections), \
                 patch("ai_workflow.workspace_retrieval.allocate_repository_budgets", return_value=budgets), \
                 patch("ai_workflow.workspace_retrieval.aggregate_workspace_fingerprint", return_value={"fingerprint": "workspace-fp"}), \
                 patch("ai_workflow.workspace_retrieval.gather_detailed_async", new=fake_gather):
                result = asyncio.run(gather_workspace_detailed_async(workspace, "fix payments", decision, parent, config, providers))

            self.assertEqual([item.metadata["repository_id"] for item in result.items], ["repo-a", "repo-b"])
            self.assertEqual(len(result.items), 2, "same text from different repos must not dedupe away provenance")
            for item in result.items:
                self.assertIn("repository_path", item.metadata)
                self.assertIn("repository_fingerprint", item.metadata)
                self.assertEqual(item.metadata["repository_id"], item.provenance["repository_id"])
                self.assertNotIn("workspace_root", item.provenance)
                self.assertNotIn("root", item.provenance)
            self.assertEqual(result.diagnostics["workspace_fingerprint"], "workspace-fp")
            self.assertEqual(result.diagnostics["repositories_searched"], ["repo-a", "repo-b"])
            self.assertEqual(result.diagnostics["repositories_skipped"], ["repo-c"])
            self.assertLessEqual(result.diagnostics["budget"]["used_context_chars"], 1000)
            self.assertEqual(result.diagnostics["budget"]["allocated_context_chars"], 1000)
            self.assertEqual(result.diagnostics["primary_retrieval"]["retrieval_intent"], "mixed")

    def test_global_deadline_marks_slow_repository_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            repo = workspace / "backend"
            repo.mkdir()
            candidate = RepositoryCandidate(repo, "repo-a", "backend", None, "fp", (), False)
            selection = RepositorySelection(candidate, 10.0, 1, True, ("identity_match",))
            parent = ContextBudget(100, 20, 300, {"hot_cache": 30, "lightweight": 90, "crg": 120, "source_fallback": 60})
            repo_budget = RepositoryBudget("repo-a", 1, 1.0, parent)
            config = default_config()
            config["workspace"]["retrieval"]["deadline_seconds"] = 0.01
            providers = ProviderStatus(False, False, False, False, False)
            decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
            calls = 0

            async def slow(*args, **kwargs):
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.05)
                return [], {}

            with patch("ai_workflow.workspace_retrieval.build_repository_candidates", return_value=[candidate]), \
                 patch("ai_workflow.workspace_retrieval.select_repositories", return_value=[selection]), \
                 patch("ai_workflow.workspace_retrieval.allocate_repository_budgets", return_value=[repo_budget]), \
                 patch("ai_workflow.workspace_retrieval.aggregate_workspace_fingerprint", return_value={"fingerprint": "fp"}), \
                 patch("ai_workflow.workspace_retrieval.gather_detailed_async", new=slow):
                result = asyncio.run(gather_workspace_detailed_async(workspace, "task", decision, parent, config, providers))

            self.assertEqual(calls, 1)
            self.assertTrue(result.diagnostics["scheduler"]["deadline_exceeded"])
            self.assertEqual(result.diagnostics["repository_results"]["repo-a"]["status"], "deadline")

    def test_stage3_ten_repo_fixture(self):
        import json
        import subprocess

        from ai_workflow.benchmark import repository_metrics
        from ai_workflow.repository_registry import refresh_registry, set_repository_included

        def git(repo: Path, *args: str) -> None:
            subprocess.run(
                ["git", "-C", str(repo), *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            config = default_config()
            config["workspace"]["max_roots"] = 12
            for index in range(10):
                repo = workspace / f"service-{index}"
                repo.mkdir()
                subprocess.run(
                    ["git", "init", "-q", str(repo)],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                git(repo, "config", "user.email", "stage3@example.invalid")
                git(repo, "config", "user.name", "Stage3 Test")
                source = repo / "internal" / "payment"
                source.mkdir(parents=True)
                body = (
                    "def ProcessPayment():\n    return 'ok'\n"
                    if index == 7
                    else f"def unrelated_{index}():\n    return {index}\n"
                )
                (source / "service.py").write_text(body, encoding="utf-8")
                git(repo, "add", ".")
                git(repo, "commit", "-qm", "fixture")

            refresh_registry(workspace, max_depth=2, config=config)
            for index in range(10):
                set_repository_included(workspace, f"service-{index}", True, config)

            generated = workspace / "ai-workspace" / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            (generated / "symbol-index.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "ProcessPayment",
                        "file": "service-7/internal/payment/service.py",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (generated / "endpoint-index.jsonl").write_text("", encoding="utf-8")

            providers = ProviderStatus(False, False, False, False, False)
            decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["fixture"], False, 0.9)
            parent = ContextBudget(
                500,
                100,
                2000,
                {"hot_cache": 200, "lightweight": 600, "crg": 800, "source_fallback": 400},
            )
            calls = []

            async def fake_gather(root, query, decision, budget, config, providers, symbol=None, endpoint=None, changed_files=None, **kwargs):
                calls.append(kwargs.get("repository_path"))
                return [
                    ContextItem(
                        "targeted_source",
                        "ProcessPayment implementation",
                        1.0,
                        False,
                        {"file": "internal/payment/service.py"},
                    )
                ], {
                    "retrieval_intent": "symbol",
                    "evidence_state": "sufficient",
                    "sufficiency": {"sufficient": True, "score": 1.0},
                    "fallbacks": [],
                    "orchestration": {},
                }

            with patch("ai_workflow.workspace_retrieval.gather_detailed_async", new=fake_gather):
                result = asyncio.run(
                    gather_workspace_detailed_async(
                        workspace,
                        "ProcessPayment",
                        decision,
                        parent,
                        config,
                        providers,
                        symbol="ProcessPayment",
                        changed_files=[],
                    )
                )

            selected_paths = [
                row["repository_path"]
                for row in result.diagnostics["selection"]
                if row["selected"]
            ]
            metrics = repository_metrics(
                list(result.items),
                ["service-7"],
                [f"service-{index}" for index in range(10) if index != 7],
                k=5,
            )
            self.assertEqual(len(result.diagnostics["selection"]), 10)
            self.assertEqual(selected_paths, ["service-7"])
            self.assertEqual(calls, ["service-7"])
            self.assertEqual(metrics["repo_recall_at_k"], 1.0)
            self.assertEqual(metrics["wrong_repo_rate"], 0.0)
            self.assertLessEqual(
                result.diagnostics["budget"]["allocated_context_chars"],
                parent.context_chars,
            )
            self.assertLessEqual(
                result.diagnostics["budget"]["used_context_chars"],
                parent.context_chars,
            )


if __name__ == "__main__":
    unittest.main()
