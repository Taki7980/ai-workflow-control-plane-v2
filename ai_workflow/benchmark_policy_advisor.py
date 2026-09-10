from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .benchmark_statistics import bootstrap_mean_ci


BASELINE_PROFILE = "adaptive_math"
LOCKED_RISKS = frozenset({"high", "critical"})


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    return value if math.isfinite(value) else default


def case_utility(
    row: dict[str, Any],
    *,
    token_penalty: float = 0.05,
    latency_penalty: float = 0.01,
) -> float | None:
    control_type = str(row.get("control_type", "")).strip().lower()
    if control_type in {"natural_no_gold", "wrong_repo"}:
        if "selective_control_correct" not in row:
            return None
        quality = 1.0 if bool(row["selective_control_correct"]) else 0.0
    else:
        file_metrics = row.get("file_retrieval")
        if not isinstance(file_metrics, dict):
            return None
        f1 = file_metrics.get("file_f1")
        if isinstance(f1, bool) or not isinstance(f1, (int, float)):
            return None
        quality = float(f1)

    budget_utilization = min(1.0, max(0.0, _number(row.get("budget_utilization"))))
    latency_seconds = min(1.0, max(0.0, _number(row.get("elapsed_ms")) / 1000.0))
    return (
        quality
        - max(0.0, float(token_penalty)) * budget_utilization
        - max(0.0, float(latency_penalty)) * latency_seconds
    )


def _context_value(row: dict[str, Any], field: str) -> str:
    current: Any = row
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return "unknown"
        current = current[part]
    if current is None or current == "":
        return "unknown"
    return str(current)


def _paired_profile_deltas(
    report: dict[str, Any],
    profile: str,
    *,
    context_field: str,
    token_penalty: float,
    latency_penalty: float,
) -> tuple[dict[str, list[float]], int]:
    results = report.get("results")
    if not isinstance(results, dict):
        raise ValueError("algorithm report must contain a results object")
    baseline = results.get(BASELINE_PROFILE)
    candidate = results.get(profile)
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError(
            f"algorithm report requires {BASELINE_PROFILE!r} and {profile!r}"
        )

    baseline_cases = baseline.get("cases") or []
    candidate_cases = candidate.get("cases") or []
    if len(baseline_cases) != len(candidate_cases):
        raise ValueError("algorithm profiles must contain the same case count")

    grouped: dict[str, list[float]] = defaultdict(list)
    locked = 0
    for left, right in zip(baseline_cases, candidate_cases):
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        if str(left.get("risk", "")).strip().lower() in LOCKED_RISKS:
            locked += 1
            continue
        base_utility = case_utility(
            left,
            token_penalty=token_penalty,
            latency_penalty=latency_penalty,
        )
        candidate_utility = case_utility(
            right,
            token_penalty=token_penalty,
            latency_penalty=latency_penalty,
        )
        if base_utility is None or candidate_utility is None:
            continue
        context = _context_value(left, context_field)
        grouped[context].append(candidate_utility - base_utility)
    return dict(grouped), locked


def build_safe_policy_advisor(
    algorithm_report: dict[str, Any],
    *,
    context_field: str = "task_type",
    minimum_samples: int = 10,
    confidence: float = 0.95,
    resamples: int = 5000,
    seed: int = 20260911,
    safety_margin: float = 0.0,
    token_penalty: float = 0.05,
    latency_penalty: float = 0.01,
) -> dict[str, Any]:
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be positive")
    results = algorithm_report.get("results")
    if not isinstance(results, dict) or BASELINE_PROFILE not in results:
        raise ValueError(
            f"algorithm report must contain baseline profile {BASELINE_PROFILE!r}"
        )

    candidates = sorted(
        profile
        for profile in results
        if profile != BASELINE_PROFILE
    )
    contexts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"arms": {}, "locked_high_risk_cases": 0}
    )
    for profile in candidates:
        grouped, locked = _paired_profile_deltas(
            algorithm_report,
            profile,
            context_field=context_field,
            token_penalty=token_penalty,
            latency_penalty=latency_penalty,
        )
        for context, deltas in grouped.items():
            stats = bootstrap_mean_ci(
                deltas,
                confidence=confidence,
                resamples=resamples,
                seed=seed,
            )
            eligible = (
                stats["n"] >= minimum_samples
                and stats["ci_low"] is not None
                and float(stats["ci_low"]) > float(safety_margin)
            )
            contexts[context]["arms"][profile] = {
                **stats,
                "eligible": eligible,
            }
        for context_payload in contexts.values():
            context_payload["locked_high_risk_cases"] = max(
                int(context_payload["locked_high_risk_cases"]),
                locked,
            )

    recommendations: dict[str, dict[str, Any]] = {}
    for context, payload in sorted(contexts.items()):
        eligible = [
            (profile, arm)
            for profile, arm in payload["arms"].items()
            if arm["eligible"]
        ]
        if eligible:
            profile, arm = max(
                eligible,
                key=lambda item: (
                    float(item[1]["ci_low"]),
                    float(item[1]["mean"]),
                    item[0],
                ),
            )
            recommendations[context] = {
                "recommended_profile": profile,
                "status": "advisory_candidate",
                "mean_utility_delta": arm["mean"],
                "lower_confidence_bound": arm["ci_low"],
                "confidence": confidence,
                "samples": arm["n"],
            }
        else:
            recommendations[context] = {
                "recommended_profile": BASELINE_PROFILE,
                "status": "baseline_retained",
                "reason": (
                    "no candidate cleared minimum samples and the "
                    "high-confidence safety margin"
                ),
            }

    return {
        "scope": "safe-retrieval-policy-advisor",
        "status": "advisory_only",
        "baseline_profile": BASELINE_PROFILE,
        "context_field": context_field,
        "minimum_samples": minimum_samples,
        "confidence": confidence,
        "bootstrap_resamples": resamples,
        "safety_margin": safety_margin,
        "reward": {
            "quality": "file_f1_or_selective_control_correctness",
            "token_penalty": token_penalty,
            "latency_penalty": latency_penalty,
        },
        "safety": {
            "locked_risks": sorted(LOCKED_RISKS),
            "runtime_override_enabled": False,
            "requires_randomized_logging_for_bandit_ope": True,
        },
        "contexts": dict(sorted(contexts.items())),
        "recommendations": recommendations,
        "warning": (
            "This is high-confidence offline policy advice, not an online "
            "contextual bandit. Do not use it for off-policy claims until "
            "logging propensities or randomized exploration data exist."
        ),
    }
