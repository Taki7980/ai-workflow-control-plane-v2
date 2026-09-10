from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def latency_percentiles(values: Iterable[float]) -> dict[str, float | None]:
    """Return deterministic nearest-rank p50/p95/p99 values."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"p50": None, "p95": None, "p99": None}

    def percentile(q: float) -> float:
        rank = max(1, math.ceil(q * len(ordered)))
        return float(ordered[min(rank, len(ordered)) - 1])

    return {"p50": percentile(0.50), "p95": percentile(0.95), "p99": percentile(0.99)}


def _minimum_failure(
    metric: str,
    floor: Any,
    actual: Any,
    *,
    query_type: str | None = None,
) -> dict[str, Any] | None:
    expected = _number(floor)
    observed = _number(actual)
    if expected is None:
        return None
    if observed is not None and observed >= expected:
        return None
    failure: dict[str, Any] = {
        "kind": "minimum",
        "metric": metric,
        "minimum": expected,
        "actual": observed,
    }
    if query_type is not None:
        failure["query_type"] = query_type
    return failure


def check_regression(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compare a benchmark result with an explicit, versioned regression policy."""

    if int(baseline.get("schema_version", 0) or 0) != 1:
        raise ValueError("unsupported benchmark baseline schema_version")

    failures: list[dict[str, Any]] = []
    checked = 0
    summary = current.get("summary") if isinstance(current.get("summary"), dict) else {}

    for metric, floor in (baseline.get("minimum") or {}).items():
        checked += 1
        failure = _minimum_failure(str(metric), floor, summary.get(metric))
        if failure:
            failures.append(failure)

    for metric, policy in (baseline.get("maximum_regression") or {}).items():
        if not isinstance(policy, dict):
            continue
        reference = _number(policy.get("baseline"))
        tolerance = _number(policy.get("relative_tolerance"))
        actual = _number(summary.get(metric))
        direction = str(policy.get("direction", "higher")).lower()
        if reference is None or tolerance is None:
            continue
        if tolerance < 0:
            raise ValueError(f"negative relative_tolerance for {metric}")
        if direction not in {"higher", "lower"}:
            raise ValueError(f"invalid direction for {metric}: {direction}")
        checked += 1
        if direction == "higher":
            limit = reference * (1 - tolerance)
            regressed = actual is None or actual < limit
        else:
            limit = reference * (1 + tolerance)
            regressed = actual is None or actual > limit
        if regressed:
            failures.append(
                {
                    "kind": "relative_regression",
                    "metric": str(metric),
                    "direction": direction,
                    "baseline": reference,
                    "relative_tolerance": tolerance,
                    "limit": limit,
                    "actual": actual,
                }
            )

    raw_groups = current.get("by_query_type")
    current_groups = raw_groups if isinstance(raw_groups, dict) else {}
    for query_type, floors in (baseline.get("by_query_type") or {}).items():
        if not isinstance(floors, dict):
            continue
        raw_group = current_groups.get(query_type)
        group = raw_group if isinstance(raw_group, dict) else {}
        for metric, floor in floors.items():
            if floor is None:
                continue
            checked += 1
            failure = _minimum_failure(
                str(metric),
                floor,
                group.get(metric),
                query_type=str(query_type),
            )
            if failure:
                failures.append(failure)

    return {"ok": not failures, "checked": checked, "failures": failures}
