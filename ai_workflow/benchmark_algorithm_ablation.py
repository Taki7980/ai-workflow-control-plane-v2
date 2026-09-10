from __future__ import annotations

import copy
from typing import Any

from .benchmark import run_benchmark


ALGORITHM_PROFILE_ORDER = (
    "adaptive_math",
    "source_rank",
    "bm25_rank",
    "rrf_only",
    "rrf_mmr_050",
    "rrf_mmr_090",
    "selector_off",
    "fixed_budget",
    "no_early_stop",
)


def algorithm_profile_config(
    config: dict[str, Any],
    profile: str,
) -> dict[str, Any]:
    name = str(profile).strip().lower()
    if name not in ALGORITHM_PROFILE_ORDER:
        raise ValueError(
            f"unknown algorithm profile {profile!r}; "
            f"expected one of {ALGORITHM_PROFILE_ORDER}"
        )

    out = copy.deepcopy(config)
    context = out.setdefault("context", {})
    experiments = context.setdefault("experiments", {})
    selector = context.setdefault("selector", {})
    adaptive_budget = context.setdefault("adaptive_budget", {})

    if name == "adaptive_math":
        return out
    if name == "source_rank":
        experiments["hybrid_ranker"] = "source"
    elif name == "bm25_rank":
        experiments["hybrid_ranker"] = "bm25"
    elif name == "rrf_only":
        experiments["hybrid_ranker"] = "rrf"
    elif name == "rrf_mmr_050":
        experiments["hybrid_ranker"] = "rrf_mmr"
        experiments["mmr_lambda"] = 0.50
    elif name == "rrf_mmr_090":
        experiments["hybrid_ranker"] = "rrf_mmr"
        experiments["mmr_lambda"] = 0.90
    elif name == "selector_off":
        selector["enabled"] = False
    elif name == "fixed_budget":
        adaptive_budget["enabled"] = False
    elif name == "no_early_stop":
        experiments["disable_early_sufficiency_gate"] = True

    return out


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    key: str,
) -> float | None:
    left = _number(baseline.get(key))
    right = _number(candidate.get(key))
    if left is None or right is None:
        return None
    return round(right - left, 4)


def _result_delta(
    adaptive: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    baseline = adaptive.get("summary") or {}
    candidate = result.get("summary") or {}
    keys = (
        "mean_file_precision_at_k",
        "mean_file_recall_at_k",
        "mean_file_mrr",
        "mean_file_ndcg_at_k",
        "mean_file_f1",
        "mean_file_yield_per_1k_tokens",
        "selective_control_accuracy",
        "mean_estimated_context_tokens",
        "mean_budget_utilization",
        "mean_elapsed_ms",
        "sufficiency_rate",
        "fallback_rate",
    )
    return {key: _delta(baseline, candidate, key) for key in keys}


def run_algorithm_ablation_suite(
    root,
    config: dict[str, Any],
    tasks: list[dict[str, Any]],
    profiles: list[str] | tuple[str, ...] | None = None,
    *,
    require_frozen_snapshot: bool = False,
    require_research_protocol: bool = False,
) -> dict[str, Any]:
    requested = list(profiles or ALGORITHM_PROFILE_ORDER)
    normalized = list(
        dict.fromkeys(str(profile).strip().lower() for profile in requested)
    )
    if not normalized:
        raise ValueError("at least one algorithm profile is required")
    for profile in normalized:
        if profile not in ALGORITHM_PROFILE_ORDER:
            raise ValueError(
                f"unknown algorithm profile {profile!r}; "
                f"expected one of {ALGORITHM_PROFILE_ORDER}"
            )

    results: dict[str, dict[str, Any]] = {}
    for profile in normalized:
        results[profile] = run_benchmark(
            root,
            algorithm_profile_config(config, profile),
            tasks,
            require_frozen_snapshot=require_frozen_snapshot,
            require_research_protocol=require_research_protocol,
        )

    adaptive = results.get("adaptive_math")
    deltas = (
        {
            profile: _result_delta(adaptive, result)
            for profile, result in results.items()
            if profile != "adaptive_math"
        }
        if adaptive is not None
        else {}
    )

    return {
        "scope": "retrieval-algorithm-ablation-suite",
        "profiles": normalized,
        "results": results,
        "delta_vs_adaptive_math": deltas,
        "note": (
            "Profiles alter one retrieval-math or context-selection mechanism "
            "at a time while leaving normal production defaults unchanged."
        ),
    }
