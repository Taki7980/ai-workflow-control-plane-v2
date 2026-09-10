from __future__ import annotations

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
