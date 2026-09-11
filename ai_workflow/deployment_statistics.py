from __future__ import annotations

import math
import random
from typing import Any

from .benchmark_statistics import percentile


DEFAULT_CLUSTER_RESAMPLES = 2000
DEFAULT_CLUSTER_SEED = 20260911


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _row_score(row: dict[str, Any]) -> float | None:
    deployment = row.get("deployment")
    outcome = row.get("outcome")
    if not isinstance(deployment, dict) or not isinstance(outcome, dict):
        return None
    if not bool(outcome.get("verified")):
        return None
    assignment = str(deployment.get("assignment", ""))
    if assignment not in {"candidate", "control"}:
        return None
    probability = _number(deployment.get("candidate_probability"))
    reward = _number(outcome.get("reward"))
    if probability is None or reward is None or not 0.0 < probability < 1.0:
        return None
    if assignment == "candidate":
        return reward / probability
    return -reward / (1.0 - probability)


def clustered_reward_difference(
    rows: list[dict[str, Any]],
    *,
    cluster_field: str = "task_fingerprint",
    confidence: float = 0.95,
    resamples: int = DEFAULT_CLUSTER_RESAMPLES,
    seed: int = DEFAULT_CLUSTER_SEED,
) -> dict[str, Any]:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    clusters: dict[str, list[float]] = {}
    invalid_rows = 0
    for index, row in enumerate(rows):
        score = _row_score(row)
        if score is None:
            invalid_rows += 1
            continue
        raw_cluster = row.get(cluster_field)
        cluster = str(raw_cluster).strip() if raw_cluster is not None else ""
        if not cluster:
            cluster = f"row:{index}"
        clusters.setdefault(cluster, []).append(score)

    cluster_names = sorted(clusters)
    values = [value for name in cluster_names for value in clusters[name]]
    if not values:
        return {
            "status": "no_valid_rows",
            "cluster_field": cluster_field,
            "rows": 0,
            "clusters": 0,
            "invalid_rows": invalid_rows,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
        }
    observed = sum(values) / len(values)
    if len(cluster_names) < 2:
        return {
            "status": "insufficient_clusters",
            "cluster_field": cluster_field,
            "rows": len(values),
            "clusters": len(cluster_names),
            "invalid_rows": invalid_rows,
            "mean": observed,
            "ci_low": None,
            "ci_high": None,
            "largest_cluster": max(len(items) for items in clusters.values()),
        }

    rng = random.Random(seed)
    bootstrap: list[float] = []
    cluster_count = len(cluster_names)
    for _ in range(resamples):
        sampled: list[float] = []
        for _index in range(cluster_count):
            name = cluster_names[rng.randrange(cluster_count)]
            sampled.extend(clusters[name])
        if sampled:
            bootstrap.append(sum(sampled) / len(sampled))
    alpha = 1.0 - confidence
    return {
        "status": "ok",
        "cluster_field": cluster_field,
        "rows": len(values),
        "clusters": cluster_count,
        "invalid_rows": invalid_rows,
        "largest_cluster": max(len(items) for items in clusters.values()),
        "mean": observed,
        "confidence": confidence,
        "resamples": resamples,
        "seed": seed,
        "ci_low": percentile(bootstrap, alpha / 2.0),
        "ci_high": percentile(bootstrap, 1.0 - alpha / 2.0),
    }
