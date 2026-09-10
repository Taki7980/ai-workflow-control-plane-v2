from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


CLI_TESTS = r'''
    def test_stage3_cli_workspace_metadata(self):
        self.template()
        packet = self.run_cli("context", "Explain this function")
        self.assertIn("lane", packet)
        self.assertIn("risk", packet)
        self.assertIn("budget", packet)
        self.assertIn("retrieval", packet)
        self.assertIn("items", packet)
        orchestration = packet["retrieval"]["workspace_orchestration"]
        budget = orchestration["budget"]
        self.assertLessEqual(budget["allocated_context_chars"], budget["parent_context_chars"])
        self.assertLessEqual(budget["used_context_chars"], budget["parent_context_chars"])

    def test_stage3_cli_multi_repo_metadata_and_prompt_are_portable(self):
        self.template()
        from ai_workflow.models import ContextItem
        from ai_workflow.workspace_retrieval import WorkspaceRetrievalResult

        primary = {
            "retrieval_intent": "mixed",
            "evidence_state": "sufficient",
            "sufficiency": {"sufficient": True, "score": 1.0},
            "fallbacks": [],
            "orchestration": {"agent_slots": 1, "superpowers_skills": [], "crg_plan": []},
            "workspace_state": {"fingerprint": "repo-fp"},
        }
        diagnostics = {
            "workspace_fingerprint": "workspace-fp",
            "repository_count": 3,
            "repositories_searched": ["repo-backend", "repo-frontend"],
            "repositories_skipped": ["repo-docs"],
            "changed_files_detected": ["backend/payments.py"],
            "selection": [
                {"repository_id": "repo-backend", "repository_path": "backend", "rank": 1, "score": 20.0, "selected": True, "reasons": ["changed_file"]},
                {"repository_id": "repo-frontend", "repository_path": "frontend", "rank": 2, "score": 12.0, "selected": True, "reasons": ["identity_match"]},
                {"repository_id": "repo-docs", "repository_path": "docs", "rank": 3, "score": 0.0, "selected": False, "reasons": ["no_relevant_signal"]},
            ],
            "repository_results": {},
            "budget": {
                "parent_context_chars": 1000,
                "allocated_context_chars": 1000,
                "used_context_chars": 120,
                "raw_repository_used_context_chars": 120,
            },
            "scheduler": {"max_workers": 2, "deadline_seconds": 12, "deadline_exceeded": False},
            "primary_retrieval": primary,
        }
        result = WorkspaceRetrievalResult(
            (
                ContextItem(
                    "targeted_source",
                    "payments.py:1 ProcessPayment",
                    1.0,
                    False,
                    {"repository_id": "repo-backend", "repository_path": "backend", "repository_fingerprint": "fp"},
                    {"repository_id": "repo-backend", "repository_path": "backend", "repository_fingerprint": "fp"},
                ),
            ),
            diagnostics,
        )
        with patch("ai_workflow.cli.gather_workspace_detailed", return_value=result):
            packet = self.run_cli("brief", "Fix typo in README")
            prompt = self.run_cli_text("brief", "Fix typo in README", "--format", "prompt")

        orchestration = packet["retrieval"]["workspace_orchestration"]
        self.assertEqual(orchestration["workspace_fingerprint"], "workspace-fp")
        self.assertEqual(orchestration["repositories_searched"], ["repo-backend", "repo-frontend"])
        self.assertEqual(packet["changed_files_detected"], ["backend/payments.py"])
        self.assertLessEqual(orchestration["budget"]["allocated_context_chars"], orchestration["budget"]["parent_context_chars"])
        self.assertIn("[REPOSITORIES] selected=backend, frontend skipped=docs", prompt)
        self.assertIn("[REPO_BUDGET] allocated=1000 used=120", prompt)
        self.assertNotIn(str(self.root.resolve()), prompt)
'''


BENCHMARK_TESTS = r'''
    def test_stage3_metric_identity(self):
        from ai_workflow.benchmark import repository_metrics

        items = [
            ContextItem("source", "left evidence", metadata={"repository_path": "left/api", "file": "service.py"}),
            ContextItem("source", "right evidence", metadata={"repository_path": "right/api", "file": "service.py"}),
        ]
        first = repository_metrics(items, ["left/api"], ["right/api"], k=1)
        both = repository_metrics(items, ["left/api"], ["right/api"], k=2)
        self.assertEqual(first["repo_recall_at_k"], 1.0)
        self.assertEqual(first["wrong_repo_rate"], 0.0)
        self.assertEqual(both["wrong_repo_rate"], 0.5)

    def test_stage3_metric_files(self):
        from ai_workflow.benchmark import file_recall

        items = [
            ContextItem(
                "source",
                "payment implementation",
                metadata={"repository_path": "backend", "file": "internal/payment/service.go"},
            )
        ]
        self.assertEqual(file_recall(items, ["internal/payment/service.go"], k=5), 1.0)
        self.assertEqual(file_recall(items, ["backend/internal/payment/service.go"], k=5), 1.0)
        self.assertEqual(file_recall(items, ["service.go"], k=5), 0.0)
        self.assertIsNone(file_recall(items, [], k=5))

    def test_stage3_metric_unlabeled_repo_case(self):
        from ai_workflow.benchmark import repository_metrics

        self.assertIsNone(repository_metrics([], [], [], k=5))
'''


WORKSPACE_TEST = r'''
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
'''


BENCHMARK = r'''from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path

from .budget import budget_for
from .classifier import classify
from .config import estimate_tokens
from .models import ContextItem
from .providers import detect, execution_provider, model_tier
from .workspace_retrieval import gather_workspace_detailed


def retrieval_metrics(items: list, relevant_patterns: list[str], k: int = 5) -> dict | None:
    patterns = [pattern.casefold() for pattern in relevant_patterns if pattern.strip()]
    if not patterns:
        return None
    cutoff = max(1, int(k))
    ranked = items[:cutoff]
    texts = [item.text.casefold() for item in ranked]
    relevance = [int(any(pattern in text for pattern in patterns)) for text in texts]
    first_relevant = next((rank for rank, value in enumerate(relevance, 1) if value), None)
    unmatched = set(range(len(patterns)))
    next_position = 1
    dcg = 0.0
    for item_rank, text in enumerate(texts, 1):
        for index in [i for i in sorted(unmatched) if patterns[i] in text]:
            position = max(item_rank, next_position)
            dcg += 1.0 / math.log2(position + 1)
            next_position = position + 1
            unmatched.remove(index)
    covered = len(patterns) - len(unmatched)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, len(patterns) + 1))
    return {
        "k": cutoff,
        "relevant_items": sum(relevance),
        "matched_patterns": covered,
        "relevant_item_density": sum(relevance) / max(1, len(ranked)),
        "precision_at_k": sum(relevance) / cutoff,
        "recall_at_k": covered / len(patterns),
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
    }


def _normalize_portable(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    if text == ".":
        return "."
    return text.strip("/")


def _item_repository_path(item: ContextItem) -> str:
    for container in (item.metadata, item.provenance):
        value = container.get("repository_path")
        if value:
            return _normalize_portable(value)
    return ""


def _item_file_paths(item: ContextItem) -> set[str]:
    repository_path = _item_repository_path(item)
    paths: set[str] = set()
    for container in (item.metadata, item.provenance):
        for key in ("file", "path"):
            value = container.get(key)
            if not value:
                continue
            local = _normalize_portable(value)
            if not local:
                continue
            paths.add(local)
            if repository_path and repository_path != ".":
                paths.add(f"{repository_path}/{local}")
    return paths


def repository_metrics(
    items: list[ContextItem],
    expected: list[str],
    forbidden: list[str],
    k: int = 5,
) -> dict | None:
    expected_set = {_normalize_portable(value) for value in expected if str(value).strip()}
    forbidden_set = {_normalize_portable(value) for value in forbidden if str(value).strip()}
    if not expected_set and not forbidden_set:
        return None
    cutoff = max(1, int(k))
    ranked = items[:cutoff]
    observed = [_item_repository_path(item) for item in ranked]
    observed = [value for value in observed if value]
    repo_recall = (
        len(expected_set & set(observed)) / len(expected_set)
        if expected_set
        else None
    )
    wrong_repo_rate = (
        sum(value in forbidden_set for value in observed) / max(1, len(observed))
        if forbidden_set
        else None
    )
    return {
        "k": cutoff,
        "repo_recall_at_k": repo_recall,
        "wrong_repo_rate": wrong_repo_rate,
    }


def file_recall(items: list[ContextItem], relevant_files: list[str], k: int = 5) -> float | None:
    gold = {_normalize_portable(value) for value in relevant_files if str(value).strip()}
    if not gold:
        return None
    observed: set[str] = set()
    for item in items[: max(1, int(k))]:
        observed.update(_item_file_paths(item))
    return len(gold & observed) / len(gold)


def _mean(rows: list[dict], key: str):
    values = [row[key] for row in rows if row.get(key) is not None]
    return round(statistics.mean(values), 4) if values else None


def run_benchmark(root: Path, config: dict, tasks: list[dict]) -> dict:
    providers = detect(root, config)
    rows = []
    for case in tasks:
        task = str(case.get("task", "")).strip()
        if not task:
            continue
        start = time.perf_counter()
        decision = classify(task, config)
        budget = budget_for(decision.lane, config)
        workspace_result = gather_workspace_detailed(
            root,
            task,
            decision,
            budget,
            config,
            providers,
            case.get("symbol"),
            case.get("endpoint"),
            case.get("changed_files") or [],
        )
        items = list(workspace_result.items)
        workspace = workspace_result.diagnostics
        retrieval = dict(workspace.get("primary_retrieval") or {})
        retrieval["workspace_orchestration"] = workspace
        sufficiency = retrieval.get("sufficiency") or {}
        fallbacks = retrieval.get("fallbacks") or []
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        used = estimate_tokens("\n".join(item.text for item in items))
        workspace_budget = workspace.get("budget") or {}
        allocated_chars = int(workspace_budget.get("allocated_context_chars") or 0)
        used_chars = int(workspace_budget.get("used_context_chars") or 0)
        budget_conserved = allocated_chars <= budget.context_chars and used_chars <= budget.context_chars
        row = {
            "task": task,
            "query_type": case.get("query_type", "unclassified"),
            "lane": decision.lane.value,
            "risk": decision.risk.value,
            "routing_confidence": decision.confidence,
            "execution_provider": execution_provider(decision.lane, config, providers),
            "model_tier": model_tier(decision, config),
            "retrieval_intent": retrieval.get("retrieval_intent", "unknown"),
            "retrieval_sufficient": bool(sufficiency.get("sufficient", False)),
            "retrieval_sufficiency_score": float(sufficiency.get("score", 0.0)),
            "evidence_state": retrieval.get("evidence_state"),
            "selector_mode": (retrieval.get("selector") or {}).get("mode"),
            "workspace_fingerprint": workspace.get("workspace_fingerprint")
            or (retrieval.get("workspace_state") or {}).get("fingerprint"),
            "orchestration_complexity_score": (retrieval.get("orchestration") or {}).get("complexity_score"),
            "fallbacks": fallbacks,
            "context_sources": list(dict.fromkeys(item.source for item in items)),
            "estimated_context_tokens": used,
            "budget_tokens": budget.estimated_tokens,
            "budget_utilization": round(used / budget.estimated_tokens, 4) if budget.estimated_tokens else 0,
            "elapsed_ms": elapsed_ms,
            "repositories_searched": len(workspace.get("repositories_searched") or []),
            "allocated_context_chars": allocated_chars,
            "used_context_chars": used_chars,
            "budget_conserved": budget_conserved,
        }
        if case.get("expected_lane"):
            row["lane_correct"] = decision.lane.value == case["expected_lane"]
        if case.get("expected_intent"):
            row["intent_correct"] = retrieval.get("retrieval_intent") == case["expected_intent"]
        expected_evidence = case.get("expected_evidence_state")
        if expected_evidence:
            row["evidence_state_correct"] = retrieval.get("evidence_state") == expected_evidence
            if case.get("no_gold") and expected_evidence == "abstain":
                row["abstention_correct"] = retrieval.get("evidence_state") == "abstain"
        metrics = retrieval_metrics(items, case.get("relevant_context") or [], int(case.get("retrieval_k", 5)))
        if metrics:
            metrics["matched_patterns_per_1k_tokens"] = round(
                metrics["matched_patterns"] * 1000 / max(1, used), 4
            )
            row["retrieval"] = metrics
        repo_metrics = repository_metrics(
            items,
            case.get("expected_repositories") or [],
            case.get("forbidden_repositories") or [],
            int(case.get("retrieval_k", 5)),
        )
        if repo_metrics:
            row.update(repo_metrics)
        file_metric = file_recall(
            items,
            case.get("relevant_files") or [],
            int(case.get("retrieval_k", 5)),
        )
        if file_metric is not None:
            row["file_recall_at_k"] = file_metric
        rows.append(row)

    lane_rows = [row for row in rows if "lane_correct" in row]
    intent_rows = [row for row in rows if "intent_correct" in row]
    evidence_rows = [row for row in rows if "evidence_state_correct" in row]
    abstention_rows = [row for row in rows if "abstention_correct" in row]
    retrieval_rows = [row["retrieval"] for row in rows if "retrieval" in row]
    groups = defaultdict(list)
    for row in rows:
        groups[row["query_type"]].append(row)
    by_query_type = {}
    for name, group in sorted(groups.items()):
        retrieval_group = [row["retrieval"] for row in group if "retrieval" in row]
        by_query_type[name] = {
            "cases": len(group),
            "lane_accuracy": round(
                sum(row.get("lane_correct", False) for row in group if "lane_correct" in row)
                / max(1, sum("lane_correct" in row for row in group)),
                4,
            )
            if any("lane_correct" in row for row in group)
            else None,
            "intent_accuracy": round(
                sum(row.get("intent_correct", False) for row in group if "intent_correct" in row)
                / max(1, sum("intent_correct" in row for row in group)),
                4,
            )
            if any("intent_correct" in row for row in group)
            else None,
            "mean_recall_at_k": _mean(retrieval_group, "recall_at_k"),
            "mean_mrr": _mean(retrieval_group, "mrr"),
            "mean_relevant_item_density": _mean(retrieval_group, "relevant_item_density"),
            "mean_pattern_yield_per_1k_tokens": _mean(retrieval_group, "matched_patterns_per_1k_tokens"),
        }

    summary = {
        "cases": len(rows),
        "mean_estimated_context_tokens": round(
            statistics.mean([row["estimated_context_tokens"] for row in rows]), 2
        )
        if rows
        else 0,
        "mean_budget_utilization": round(
            statistics.mean([row["budget_utilization"] for row in rows]), 4
        )
        if rows
        else 0,
        "mean_elapsed_ms": round(statistics.mean([row["elapsed_ms"] for row in rows]), 2)
        if rows
        else 0,
        "lane_accuracy": round(sum(row["lane_correct"] for row in lane_rows) / len(lane_rows), 4)
        if lane_rows
        else None,
        "intent_accuracy": round(
            sum(row["intent_correct"] for row in intent_rows) / len(intent_rows), 4
        )
        if intent_rows
        else None,
        "evidence_state_accuracy": round(
            sum(row["evidence_state_correct"] for row in evidence_rows) / len(evidence_rows), 4
        )
        if evidence_rows
        else None,
        "abstention_accuracy": round(
            sum(row["abstention_correct"] for row in abstention_rows) / len(abstention_rows), 4
        )
        if abstention_rows
        else None,
        "mean_precision_at_k": _mean(retrieval_rows, "precision_at_k"),
        "mean_recall_at_k": _mean(retrieval_rows, "recall_at_k"),
        "mean_mrr": _mean(retrieval_rows, "mrr"),
        "mean_ndcg_at_k": _mean(retrieval_rows, "ndcg_at_k"),
        "mean_relevant_item_density": _mean(retrieval_rows, "relevant_item_density"),
        "mean_pattern_yield_per_1k_tokens": _mean(retrieval_rows, "matched_patterns_per_1k_tokens"),
        "sufficiency_rate": round(
            sum(bool(row["retrieval_sufficient"]) for row in rows) / len(rows), 4
        )
        if rows
        else 0,
        "fallback_rate": round(sum(bool(row["fallbacks"]) for row in rows) / len(rows), 4)
        if rows
        else 0,
    }
    repo_recall_rows = [{"value": row.get("repo_recall_at_k")} for row in rows if "repo_recall_at_k" in row]
    wrong_repo_rows = [{"value": row.get("wrong_repo_rate")} for row in rows if "wrong_repo_rate" in row]
    file_recall_rows = [{"value": row.get("file_recall_at_k")} for row in rows if "file_recall_at_k" in row]
    if repo_recall_rows:
        summary["mean_repo_recall_at_k"] = _mean(repo_recall_rows, "value")
    if wrong_repo_rows:
        summary["mean_wrong_repo_rate"] = _mean(wrong_repo_rows, "value")
    if file_recall_rows:
        summary["mean_file_recall_at_k"] = _mean(file_recall_rows, "value")

    return {
        "scope": "routing-and-context-only",
        "warning": "Estimated context tokens are not provider-billed tokens. Retrieval metrics measure supplied gold patterns and do not prove downstream task correctness.",
        "providers": providers.to_dict(),
        "cases": rows,
        "by_query_type": by_query_type,
        "summary": summary,
    }


def load_tasks(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("benchmark task file must be a JSON array")
    return [item for item in data if isinstance(item, dict)]
'''


def write_tests() -> None:
    cli_path = Path("tests/test_cli.py")
    cli = cli_path.read_text(encoding="utf-8")
    if "test_stage3_cli_workspace_metadata" not in cli:
        cli = _replace_once(
            cli,
            "from pathlib import Path\n",
            "from pathlib import Path\nfrom unittest.mock import patch\n",
            "cli patch import",
        )
        cli = _replace_once(
            cli,
            '\n\nif __name__ == "__main__":\n',
            CLI_TESTS + '\n\nif __name__ == "__main__":\n',
            "cli tests marker",
        )
        cli_path.write_text(cli, encoding="utf-8")

    benchmark_path = Path("tests/test_benchmark_metrics.py")
    benchmark = benchmark_path.read_text(encoding="utf-8")
    if "test_stage3_metric_identity" not in benchmark:
        benchmark = _replace_once(
            benchmark,
            '\n\nif __name__ == "__main__":\n',
            BENCHMARK_TESTS + '\n\nif __name__ == "__main__":\n',
            "benchmark tests marker",
        )
        benchmark_path.write_text(benchmark, encoding="utf-8")

    workspace_path = Path("tests/test_workspace_retrieval.py")
    workspace = workspace_path.read_text(encoding="utf-8")
    if "test_stage3_ten_repo_fixture" not in workspace:
        workspace = _replace_once(
            workspace,
            '\n\nif __name__ == "__main__":\n',
            WORKSPACE_TEST + '\n\nif __name__ == "__main__":\n',
            "workspace tests marker",
        )
        workspace_path.write_text(workspace, encoding="utf-8")


def apply_cli() -> None:
    path = Path("ai_workflow/cli.py")
    text = path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "from .adaptive_broker import gather_detailed\n",
        "from .workspace_retrieval import gather_workspace_detailed\n",
        "cli retrieval import",
    )
    text = _replace_once(
        text,
        '''    fingerprint = (retrieval.get("workspace_state") or {}).get("fingerprint", "unknown")
    ctx_text = "\\n".join(i["text"] for i in packet.get("context", []) if i.get("text"))
''',
        '''    workspace_orchestration = retrieval.get("workspace_orchestration", {}) or {}
    fingerprint = (
        workspace_orchestration.get("workspace_fingerprint")
        or (retrieval.get("workspace_state") or {}).get("fingerprint", "unknown")
    )
    multi_repo = int(workspace_orchestration.get("repository_count") or 0) > 1
    selection = workspace_orchestration.get("selection") or []
    selected_paths = [
        str(row.get("repository_path"))
        for row in selection
        if row.get("selected") and row.get("repository_path")
    ]
    skipped_paths = [
        str(row.get("repository_path"))
        for row in selection
        if not row.get("selected") and row.get("repository_path")
    ]
    repo_budget = workspace_orchestration.get("budget") or {}
    ctx_text = "\\n".join(i["text"] for i in packet.get("context", []) if i.get("text"))
''',
        "brief workspace formatting state",
    )
    text = _replace_once(
        text,
        '''        ]
        return "\\n".join(lines)
    lines = [
''',
        '''        ]
        if multi_repo:
            lines[9:9] = [
                f"**Repositories**: selected {', '.join(selected_paths) or 'none'}; skipped {', '.join(skipped_paths) or 'none'}",
                f"**Repo budget**: allocated={repo_budget.get('allocated_context_chars', 0)} used={repo_budget.get('used_context_chars', 0)}",
            ]
        return "\\n".join(lines)
    lines = [
''',
        "markdown repo formatting",
    )
    text = _replace_once(
        text,
        '''    ]
    if packet.get("context"):
        lines += ["[CONTEXT_START]", ctx_text, "[CONTEXT_END]"]
''',
        '''    ]
    if multi_repo:
        lines += [
            f"[REPOSITORIES] selected={', '.join(selected_paths) or 'none'} skipped={', '.join(skipped_paths) or 'none'}",
            f"[REPO_BUDGET] allocated={repo_budget.get('allocated_context_chars', 0)} used={repo_budget.get('used_context_chars', 0)}",
        ]
    if packet.get("context"):
        lines += ["[CONTEXT_START]", ctx_text, "[CONTEXT_END]"]
''',
        "prompt repo formatting",
    )
    text = _replace_once(
        text,
        '''    changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        changed,
        write_telemetry=(decision.lane.value != "answer" or args.trace),
    )
''',
        '''    explicit_changed = list(args.changed_file) if args.changed_file else None
    workspace_result = gather_workspace_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        explicit_changed,
        write_telemetry=(decision.lane.value != "answer" or args.trace),
    )
    items = list(workspace_result.items)
    workspace_orchestration = workspace_result.diagnostics
    retrieval = dict(workspace_orchestration.get("primary_retrieval") or {})
    retrieval["workspace_orchestration"] = workspace_orchestration
    changed = list(workspace_orchestration.get("changed_files_detected") or [])
''',
        "cmd_brief retrieval",
    )
    text = _replace_once(
        text,
        '''    changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        changed,
        write_telemetry=args.trace,
    )
''',
        '''    explicit_changed = list(args.changed_file) if args.changed_file else None
    workspace_result = gather_workspace_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        explicit_changed,
        write_telemetry=args.trace,
    )
    items = list(workspace_result.items)
    workspace_orchestration = workspace_result.diagnostics
    retrieval = dict(workspace_orchestration.get("primary_retrieval") or {})
    retrieval["workspace_orchestration"] = workspace_orchestration
''',
        "cmd_context retrieval",
    )
    path.write_text(text, encoding="utf-8")


def apply_impl() -> None:
    apply_cli()
    Path("ai_workflow/benchmark.py").write_text(BENCHMARK, encoding="utf-8")


def apply_docs() -> None:
    workflow_path = Path(".github/workflows/tests.yml")
    workflow = workflow_path.read_text(encoding="utf-8")
    if "ai_workflow/workspace_selector.py" not in workflow:
        workflow = _replace_once(
            workflow,
            '''          ai_workflow/provider_runner.py
          scripts/check_benchmark_regression.py
''',
            '''          ai_workflow/provider_runner.py
          ai_workflow/workspace_selector.py
          ai_workflow/workspace_budget.py
          ai_workflow/workspace_retrieval.py
          scripts/check_benchmark_regression.py
''',
            "ruff stage3 targets",
        )
        workflow = _replace_once(
            workflow,
            '''          ai_workflow/api.py
          ai_workflow/provider_runner.py
''',
            '''          ai_workflow/api.py
          ai_workflow/provider_runner.py
          ai_workflow/workspace_selector.py
          ai_workflow/workspace_budget.py
          ai_workflow/workspace_retrieval.py
''',
            "mypy stage3 targets",
        )
        workflow_path.write_text(workflow, encoding="utf-8")

    docs_path = Path("docs/multi-repo-workspace-registry.md")
    docs = docs_path.read_text(encoding="utf-8")
    heading = "## Stage 3 retrieval orchestration"
    if heading not in docs:
        section = r'''

## Stage 3 retrieval orchestration

Accepted repositories are retrieval **candidates**, not repositories that are searched automatically. `brief` and `context` score the accepted candidate set deterministically and search at most three repositories by default. A strong secondary-repository signal can outrank the primary repository; unrelated accepted repositories remain skipped.

All selected repositories share one parent context budget. The rank-1 repository receives the strongest allocation, per-repository slices are bounded, and the sum of allocations and final merged evidence never exceeds the parent budget. Repository retrieval runs with at most three workers under one 12-second monotonic workspace deadline by default. A timed-out or failed repository is reported and is not retried or replaced by an unselected repository.

Changed files are partitioned to their owning repository before repository-local retrieval. Every merged context item carries portable `repository_id`, `repository_path`, and `repository_fingerprint` provenance; absolute checkout paths are not serialized into portable evidence. Identical evidence text from two repositories remains distinct because cross-repository deduplication includes repository identity.

`ai-workflow brief` and `ai-workflow context` preserve the existing retrieval fields and add `retrieval.workspace_orchestration`. That block reports the aggregate workspace fingerprint, selected and skipped repositories with selector reasons, per-repository status, context allocation and use, and scheduler/deadline diagnostics. Human-readable briefs show selected/skipped repository paths and the aggregate repository budget only when the workspace has multiple candidates.

Stage 3 intentionally does not add dependency-graph traversal, topology learning, learned routing, daemon behavior, or retry loops. Those remain later-stage work.
'''
        docs_path.write_text(docs.rstrip() + section + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("tests", "impl", "docs"))
    args = parser.parse_args()
    if args.mode == "tests":
        write_tests()
    elif args.mode == "impl":
        apply_impl()
    else:
        apply_docs()


if __name__ == "__main__":
    main()
