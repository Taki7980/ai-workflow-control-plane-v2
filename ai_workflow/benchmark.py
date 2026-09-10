from __future__ import annotations

import copy
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path

from .adaptive_broker import gather_detailed
from .benchmark_protocol import (
    file_retrieval_metrics,
    repository_control_metrics,
    resolve_case_root,
    snapshot_status,
    validate_benchmark_cases,
)
from .benchmark_trajectory import load_trajectory_events, trajectory_metrics
from .budget import budget_for
from .classifier import classify
from .config import estimate_tokens
from .providers import detect, execution_provider, model_tier


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


def _mean(rows: list[dict], key: str):
    values = [r[key] for r in rows if r.get(key) is not None]
    return round(statistics.mean(values), 4) if values else None


def _accuracy(rows: list[dict], key: str) -> float | None:
    values = [bool(row[key]) for row in rows if key in row]
    return round(sum(values) / len(values), 4) if values else None


def _isolated_case_config(config: dict) -> dict:
    out = copy.deepcopy(config)
    workspace = out.setdefault("workspace", {})
    workspace["roots"] = []
    workspace["max_roots"] = 1
    return out


def _group_summary(group: list[dict]) -> dict:
    pattern_rows = [r["retrieval"] for r in group if "retrieval" in r]
    file_rows = [r["file_retrieval"] for r in group if "file_retrieval" in r]
    trajectory_rows = [r["trajectory"] for r in group if "trajectory" in r]
    return {
        "cases": len(group),
        "lane_accuracy": _accuracy(group, "lane_correct"),
        "intent_accuracy": _accuracy(group, "intent_correct"),
        "evidence_state_accuracy": _accuracy(group, "evidence_state_correct"),
        "selective_control_accuracy": _accuracy(group, "selective_control_correct"),
        "mean_recall_at_k": _mean(pattern_rows, "recall_at_k"),
        "mean_mrr": _mean(pattern_rows, "mrr"),
        "mean_relevant_item_density": _mean(pattern_rows, "relevant_item_density"),
        "mean_pattern_yield_per_1k_tokens": _mean(
            pattern_rows, "matched_patterns_per_1k_tokens"
        ),
        "mean_file_precision_at_k": _mean(file_rows, "precision_at_k"),
        "mean_file_recall_at_k": _mean(file_rows, "recall_at_k"),
        "mean_file_mrr": _mean(file_rows, "mrr"),
        "mean_file_ndcg_at_k": _mean(file_rows, "ndcg_at_k"),
        "mean_file_f1": _mean(file_rows, "file_f1"),
        "mean_file_yield_per_1k_tokens": _mean(
            file_rows, "matched_gold_files_per_1k_tokens"
        ),
        "mean_exploration_precision": _mean(
            trajectory_rows, "exploration_precision"
        ),
        "mean_exploration_recall": _mean(
            trajectory_rows, "exploration_recall"
        ),
        "mean_utilization_precision": _mean(
            trajectory_rows, "utilization_precision"
        ),
        "mean_utilization_recall": _mean(
            trajectory_rows, "utilization_recall"
        ),
        "mean_context_utilization_rate": _mean(
            trajectory_rows, "context_utilization_rate"
        ),
        "mean_duplicate_exploration_rate": _mean(
            trajectory_rows, "duplicate_exploration_rate"
        ),
    }


def run_benchmark(
    root: Path,
    config: dict,
    tasks: list[dict],
    *,
    require_frozen_snapshot: bool = False,
    require_research_protocol: bool = False,
) -> dict:
    tasks = validate_benchmark_cases(
        tasks,
        require_research_protocol=require_research_protocol,
    )
    providers = detect(root, config)
    rows = []

    for case in tasks:
        task = str(case.get("task", "")).strip()
        case_root = resolve_case_root(root, case)
        case_config = _isolated_case_config(config)
        case_providers = detect(case_root, case_config)
        snapshot = snapshot_status(root, case)
        if require_frozen_snapshot and snapshot["status"] != "match":
            raise ValueError(
                "benchmark snapshot does not match frozen base commit: "
                f"{snapshot['repository_path']} expected={snapshot['expected_head']} "
                f"actual={snapshot['actual_head']}"
            )

        start = time.perf_counter()
        decision = classify(task, case_config)
        budget = budget_for(decision.lane, case_config)
        items, retrieval = gather_detailed(
            case_root,
            task,
            decision,
            budget,
            case_config,
            case_providers,
            case.get("symbol"),
            case.get("endpoint"),
            case.get("changed_files") or [],
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        used = estimate_tokens("\n".join(i.text for i in items))
        retrieval_k = int(case.get("retrieval_k", 5))
        control_type = str(case.get("control_type", "positive"))
        task_type = str(case.get("task_type") or case.get("query_type", "unclassified"))

        row = {
            "task": task,
            "task_type": task_type,
            "query_type": case.get("query_type", "unclassified"),
            "control_type": control_type,
            "repository_path": str(case.get("repository_path", ".")).strip() or ".",
            "snapshot": snapshot,
            "lane": decision.lane.value,
            "risk": decision.risk.value,
            "routing_confidence": decision.confidence,
            "execution_provider": execution_provider(
                decision.lane, case_config, case_providers
            ),
            "model_tier": model_tier(decision, case_config),
            "providers": case_providers.to_dict(),
            "retrieval_intent": retrieval["retrieval_intent"],
            "retrieval_sufficient": retrieval["sufficiency"]["sufficient"],
            "retrieval_sufficiency_score": retrieval["sufficiency"]["score"],
            "evidence_state": retrieval.get("evidence_state"),
            "selector_mode": (retrieval.get("selector") or {}).get("mode"),
            "workspace_fingerprint": (
                retrieval.get("workspace_state") or {}
            ).get("fingerprint"),
            "orchestration_complexity_score": (
                retrieval.get("orchestration") or {}
            ).get("complexity_score"),
            "fallbacks": retrieval["fallbacks"],
            "context_sources": list(dict.fromkeys(i.source for i in items)),
            "estimated_context_tokens": used,
            "budget_tokens": budget.estimated_tokens,
            "budget_utilization": (
                round(used / budget.estimated_tokens, 4)
                if budget.estimated_tokens
                else 0
            ),
            "elapsed_ms": elapsed_ms,
        }

        if case.get("expected_lane"):
            row["lane_correct"] = decision.lane.value == case["expected_lane"]
        if case.get("expected_intent"):
            row["intent_correct"] = (
                retrieval["retrieval_intent"] == case["expected_intent"]
            )

        expected_evidence = case.get("expected_evidence_state")
        if expected_evidence:
            row["evidence_state_correct"] = (
                retrieval.get("evidence_state") == expected_evidence
            )
            if case.get("no_gold") and expected_evidence == "abstain":
                row["abstention_correct"] = (
                    retrieval.get("evidence_state") == "abstain"
                )

        if control_type in {"natural_no_gold", "wrong_repo"}:
            expected_control_state = str(
                case.get("expected_evidence_state", "abstain")
            )
            row["selective_control_correct"] = (
                retrieval.get("evidence_state") == expected_control_state
            )

        metrics = retrieval_metrics(
            items,
            case.get("relevant_context") or [],
            retrieval_k,
        )
        if metrics:
            metrics["matched_patterns_per_1k_tokens"] = round(
                metrics["matched_patterns"] * 1000 / max(1, used),
                4,
            )
            row["retrieval"] = metrics

        file_metrics = file_retrieval_metrics(
            items,
            case.get("gold_files") or [],
            retrieval_k,
        )
        if file_metrics:
            file_metrics["matched_gold_files_per_1k_tokens"] = round(
                len(file_metrics["matched_gold_files"]) * 1000 / max(1, used),
                4,
            )
            row["file_retrieval"] = file_metrics

        repository_control = repository_control_metrics(
            items,
            case.get("forbidden_repositories") or [],
            retrieval_k,
        )
        if repository_control:
            row["repository_control"] = repository_control

        events = load_trajectory_events(root, case)
        trajectory = trajectory_metrics(
            events,
            case.get("gold_files") or [],
        )
        if trajectory:
            row["trajectory"] = trajectory

        rows.append(row)

    lane_rows = [r for r in rows if "lane_correct" in r]
    intent_rows = [r for r in rows if "intent_correct" in r]
    evidence_rows = [r for r in rows if "evidence_state_correct" in r]
    abstention_rows = [r for r in rows if "abstention_correct" in r]
    control_rows = [r for r in rows if "selective_control_correct" in r]
    retrieval_rows = [r["retrieval"] for r in rows if "retrieval" in r]
    file_rows = [r["file_retrieval"] for r in rows if "file_retrieval" in r]
    trajectory_rows = [r["trajectory"] for r in rows if "trajectory" in r]
    frozen_rows = [r for r in rows if r["snapshot"]["match"] is not None]

    by_query_groups = defaultdict(list)
    by_task_groups = defaultdict(list)
    for row in rows:
        by_query_groups[row["query_type"]].append(row)
        by_task_groups[row["task_type"]].append(row)

    by_query_type = {
        name: _group_summary(group)
        for name, group in sorted(by_query_groups.items())
    }
    by_task_type = {
        name: _group_summary(group)
        for name, group in sorted(by_task_groups.items())
    }

    return {
        "scope": "routing-and-context-only",
        "research_protocol": {
            "file_level_gold_supported": True,
            "frozen_snapshot_check_supported": True,
            "selective_controls_supported": True,
            "multi_repo_case_isolation_supported": True,
            "trajectory_utilization_metrics_supported": True,
            "task_types": [
                "code2test",
                "comment2context",
                "trace2code",
                "edit2ripple",
                "no_gold",
            ],
        },
        "warning": (
            "Estimated context tokens are not provider-billed tokens. "
            "Retrieval metrics measure supplied gold patterns/files and do not "
            "prove downstream task correctness."
        ),
        "providers": providers.to_dict(),
        "cases": rows,
        "by_query_type": by_query_type,
        "by_task_type": by_task_type,
        "summary": {
            "cases": len(rows),
            "mean_estimated_context_tokens": (
                round(statistics.mean([r["estimated_context_tokens"] for r in rows]), 2)
                if rows
                else 0
            ),
            "mean_budget_utilization": (
                round(statistics.mean([r["budget_utilization"] for r in rows]), 4)
                if rows
                else 0
            ),
            "mean_elapsed_ms": (
                round(statistics.mean([r["elapsed_ms"] for r in rows]), 2)
                if rows
                else 0
            ),
            "lane_accuracy": _accuracy(lane_rows, "lane_correct"),
            "intent_accuracy": _accuracy(intent_rows, "intent_correct"),
            "evidence_state_accuracy": _accuracy(
                evidence_rows, "evidence_state_correct"
            ),
            "abstention_accuracy": _accuracy(abstention_rows, "abstention_correct"),
            "selective_control_accuracy": _accuracy(
                control_rows, "selective_control_correct"
            ),
            "mean_precision_at_k": _mean(retrieval_rows, "precision_at_k"),
            "mean_recall_at_k": _mean(retrieval_rows, "recall_at_k"),
            "mean_mrr": _mean(retrieval_rows, "mrr"),
            "mean_ndcg_at_k": _mean(retrieval_rows, "ndcg_at_k"),
            "mean_relevant_item_density": _mean(
                retrieval_rows, "relevant_item_density"
            ),
            "mean_pattern_yield_per_1k_tokens": _mean(
                retrieval_rows, "matched_patterns_per_1k_tokens"
            ),
            "mean_file_precision_at_k": _mean(file_rows, "precision_at_k"),
            "mean_file_recall_at_k": _mean(file_rows, "recall_at_k"),
            "mean_file_mrr": _mean(file_rows, "mrr"),
            "mean_file_ndcg_at_k": _mean(file_rows, "ndcg_at_k"),
            "mean_file_f1": _mean(file_rows, "file_f1"),
            "mean_file_yield_per_1k_tokens": _mean(
                file_rows, "matched_gold_files_per_1k_tokens"
            ),
            "mean_exploration_precision": _mean(
                trajectory_rows, "exploration_precision"
            ),
            "mean_exploration_recall": _mean(
                trajectory_rows, "exploration_recall"
            ),
            "mean_utilization_precision": _mean(
                trajectory_rows, "utilization_precision"
            ),
            "mean_utilization_recall": _mean(
                trajectory_rows, "utilization_recall"
            ),
            "mean_context_utilization_rate": _mean(
                trajectory_rows, "context_utilization_rate"
            ),
            "mean_duplicate_exploration_rate": _mean(
                trajectory_rows, "duplicate_exploration_rate"
            ),
            "frozen_snapshot_match_rate": (
                round(
                    sum(bool(r["snapshot"]["match"]) for r in frozen_rows)
                    / len(frozen_rows),
                    4,
                )
                if frozen_rows
                else None
            ),
            "sufficiency_rate": (
                round(
                    sum(bool(r["retrieval_sufficient"]) for r in rows) / len(rows),
                    4,
                )
                if rows
                else 0
            ),
            "fallback_rate": (
                round(sum(bool(r["fallbacks"]) for r in rows) / len(rows), 4)
                if rows
                else 0
            ),
        },
    }


def load_tasks(
    path: Path,
    *,
    require_research_protocol: bool = False,
) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("benchmark task file must be a JSON array")
    tasks = [x for x in data if isinstance(x, dict)]
    return validate_benchmark_cases(
        tasks,
        require_research_protocol=require_research_protocol,
    )
