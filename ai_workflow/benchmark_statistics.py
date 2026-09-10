from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from typing import Any


DEFAULT_BOOTSTRAP_RESAMPLES = 5000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_RANDOM_SEED = 20260911


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    p = min(1.0, max(0.0, float(probability)))
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_mean_ci(
    values: list[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    cleaned = [float(value) for value in values if math.isfinite(float(value))]
    if not cleaned:
        return {
            "n": 0,
            "mean": None,
            "confidence": confidence,
            "ci_low": None,
            "ci_high": None,
            "resamples": 0,
        }
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    draws = max(1, int(resamples))
    mean = statistics.mean(cleaned)
    if len(cleaned) == 1:
        return {
            "n": 1,
            "mean": round(mean, 6),
            "confidence": confidence,
            "ci_low": round(mean, 6),
            "ci_high": round(mean, 6),
            "resamples": 0,
        }

    rng = random.Random(int(seed))
    size = len(cleaned)
    sampled_means = [
        statistics.mean(cleaned[rng.randrange(size)] for _ in range(size))
        for _ in range(draws)
    ]
    alpha = (1.0 - confidence) / 2.0
    return {
        "n": size,
        "mean": round(mean, 6),
        "confidence": confidence,
        "ci_low": round(percentile(sampled_means, alpha), 6),
        "ci_high": round(percentile(sampled_means, 1.0 - alpha), 6),
        "resamples": draws,
    }


def paired_effect_summary(
    deltas: list[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    cleaned = [float(value) for value in deltas if math.isfinite(float(value))]
    ci = bootstrap_mean_ci(
        cleaned,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )
    if not cleaned:
        return {
            **ci,
            "wins": 0,
            "ties": 0,
            "losses": 0,
            "win_rate": None,
            "cohen_dz": None,
        }

    wins = sum(value > 0 for value in cleaned)
    ties = sum(value == 0 for value in cleaned)
    losses = sum(value < 0 for value in cleaned)
    stdev = statistics.stdev(cleaned) if len(cleaned) > 1 else 0.0
    effect = statistics.mean(cleaned) / stdev if stdev > 0 else None
    return {
        **ci,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "win_rate": round(wins / len(cleaned), 6),
        "cohen_dz": round(effect, 6) if effect is not None else None,
    }


def _runner_trajectory(row: dict[str, Any]) -> dict[str, Any] | None:
    runner = row.get("runner")
    if not isinstance(runner, dict) or runner.get("status") != "ok":
        return None
    trajectory = runner.get("trajectory")
    return trajectory if isinstance(trajectory, dict) else None


def paired_seed_deltas(
    report: dict[str, Any],
    *,
    baseline_mode: str = "random_non_gold",
) -> dict[str, dict[str, list[float]]]:
    rows = report.get("results") or []
    by_case: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        try:
            case_index = int(raw["case_index"])
        except (KeyError, TypeError, ValueError):
            continue
        by_case[case_index][str(raw.get("seed_mode", ""))] = raw

    metric_keys = (
        "exploration_recall",
        "utilization_recall",
        "context_utilization_rate",
        "duplicate_exploration_rate",
        "post_seed_exploration_unique_files",
    )
    out: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for modes in by_case.values():
        baseline = modes.get(baseline_mode)
        if baseline is None:
            continue
        baseline_traj = _runner_trajectory(baseline)
        if baseline_traj is None:
            continue
        for mode, row in modes.items():
            if mode == baseline_mode:
                continue
            trajectory = _runner_trajectory(row)
            if trajectory is None:
                continue
            for key in metric_keys:
                left = _numeric(baseline_traj.get(key))
                right = _numeric(trajectory.get(key))
                if left is not None and right is not None:
                    out[mode][key].append(right - left)
    return {
        mode: dict(metrics)
        for mode, metrics in out.items()
    }


def _field_value(row: dict[str, Any], field: str) -> str:
    current: Any = row
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return "unknown"
        current = current[part]
    if current is None or current == "":
        return "unknown"
    return str(current)


def _subset_report(
    report: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "scope": report.get("scope"),
        "results": rows,
    }


def analyze_seed_report(
    report: dict[str, Any],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_RANDOM_SEED,
    stratify: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    paired = paired_seed_deltas(report)
    comparisons = {
        mode: {
            metric: paired_effect_summary(
                values,
                confidence=confidence,
                resamples=resamples,
                seed=seed,
            )
            for metric, values in metrics.items()
        }
        for mode, metrics in sorted(paired.items())
    }

    rows = [
        row
        for row in (report.get("results") or [])
        if isinstance(row, dict)
    ]
    stratified: dict[str, dict[str, Any]] = {}
    for field in stratify:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[_field_value(row, field)].append(row)
        stratified[field] = {
            value: {
                mode: {
                    metric: paired_effect_summary(
                        deltas,
                        confidence=confidence,
                        resamples=resamples,
                        seed=seed,
                    )
                    for metric, deltas in metrics.items()
                }
                for mode, metrics in sorted(
                    paired_seed_deltas(
                        _subset_report(report, group)
                    ).items()
                )
            }
            for value, group in sorted(groups.items())
        }

    return {
        "scope": "seed-intervention-statistics",
        "confidence": confidence,
        "bootstrap_resamples": max(1, int(resamples)),
        "random_seed": int(seed),
        "paired_against": "random_non_gold",
        "comparisons": comparisons,
        "stratified": stratified,
        "interpretation": (
            "A confidence interval entirely above zero supports improvement "
            "over the paired random-non-gold control. Intervals crossing zero "
            "are inconclusive and must not be treated as evidence of a win."
        ),
    }
