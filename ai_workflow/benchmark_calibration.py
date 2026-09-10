from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import Any


DEFAULT_CALIBRATION_FRACTION = 0.7
DEFAULT_FALSE_ACCEPT_COST = 5.0
DEFAULT_FALSE_REJECT_COST = 1.0


def _score(row: dict[str, Any]) -> float | None:
    value = row.get("retrieval_sufficiency_score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _label(row: dict[str, Any]) -> int | None:
    control_type = str(row.get("control_type", "")).strip().lower()
    if control_type == "positive":
        return 1
    if control_type in {"natural_no_gold", "wrong_repo"}:
        return 0
    return None


def _case_key(row: dict[str, Any], index: int) -> str:
    snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
    return "|".join(
        (
            str(index),
            str(row.get("task", "")),
            str(row.get("task_type", "")),
            str(row.get("repository_path", ".")),
            str(snapshot.get("expected_head", "")),
        )
    )


def _bucket(key: str) -> float:
    digest = hashlib.sha256(key.encode()).digest()
    integer = int.from_bytes(digest[:8], "big")
    return integer / float(2**64)


def deterministic_stratified_split(
    rows: list[dict[str, Any]],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fraction = float(calibration_fraction)
    if not 0.0 < fraction < 1.0:
        raise ValueError("calibration_fraction must be between 0 and 1")

    eligible: list[tuple[int, dict[str, Any], int]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        label = _label(row)
        if label is None or _score(row) is None:
            continue
        eligible.append((index, row, label))

    by_label: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, row, label in eligible:
        by_label[label].append((index, row))

    calibration: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    for label, group in sorted(by_label.items()):
        ranked = sorted(
            group,
            key=lambda pair: (
                _bucket(_case_key(pair[1], pair[0])),
                _case_key(pair[1], pair[0]),
            ),
        )
        if len(ranked) == 1:
            calibration.append(ranked[0][1])
            continue
        cutoff = min(
            len(ranked) - 1,
            max(1, int(round(len(ranked) * fraction))),
        )
        calibration.extend(row for _, row in ranked[:cutoff])
        holdout.extend(row for _, row in ranked[cutoff:])
    return calibration, holdout


def threshold_metrics(
    rows: list[dict[str, Any]],
    threshold: float,
    *,
    false_accept_cost: float = DEFAULT_FALSE_ACCEPT_COST,
    false_reject_cost: float = DEFAULT_FALSE_REJECT_COST,
) -> dict[str, Any]:
    t = float(threshold)
    fa_cost = float(false_accept_cost)
    fr_cost = float(false_reject_cost)
    if fa_cost < 0 or fr_cost < 0:
        raise ValueError("misclassification costs must be non-negative")

    tp = tn = fp = fn = 0
    scored = 0
    for row in rows:
        label = _label(row)
        score = _score(row)
        if label is None or score is None:
            continue
        prediction = 1 if score >= t else 0
        scored += 1
        if prediction == 1 and label == 1:
            tp += 1
        elif prediction == 0 and label == 0:
            tn += 1
        elif prediction == 1 and label == 0:
            fp += 1
        else:
            fn += 1

    positives = tp + fn
    negatives = tn + fp
    total_cost = fp * fa_cost + fn * fr_cost
    return {
        "threshold": round(t, 6),
        "n": scored,
        "tp": tp,
        "tn": tn,
        "false_accepts": fp,
        "false_rejects": fn,
        "true_positive_rate": (
            round(tp / positives, 6) if positives else None
        ),
        "true_negative_rate": (
            round(tn / negatives, 6) if negatives else None
        ),
        "false_accept_rate": (
            round(fp / negatives, 6) if negatives else None
        ),
        "false_reject_rate": (
            round(fn / positives, 6) if positives else None
        ),
        "balanced_accuracy": (
            round(
                (
                    (tp / positives if positives else 0.0)
                    + (tn / negatives if negatives else 0.0)
                )
                / 2.0,
                6,
            )
            if positives and negatives
            else None
        ),
        "expected_cost_per_case": (
            round(total_cost / scored, 6) if scored else None
        ),
        "total_cost": round(total_cost, 6),
    }


def candidate_thresholds(rows: list[dict[str, Any]]) -> list[float]:
    scores = sorted(
        {
            score
            for row in rows
            if (score := _score(row)) is not None
        }
    )
    if not scores:
        return []
    thresholds = {0.0, 1.0, *scores}
    for left, right in zip(scores, scores[1:]):
        thresholds.add((left + right) / 2.0)
    return sorted(thresholds)


def choose_cost_sensitive_threshold(
    rows: list[dict[str, Any]],
    *,
    false_accept_cost: float = DEFAULT_FALSE_ACCEPT_COST,
    false_reject_cost: float = DEFAULT_FALSE_REJECT_COST,
) -> dict[str, Any]:
    thresholds = candidate_thresholds(rows)
    if not thresholds:
        raise ValueError("no eligible sufficiency scores available for calibration")

    evaluations = [
        threshold_metrics(
            rows,
            threshold,
            false_accept_cost=false_accept_cost,
            false_reject_cost=false_reject_cost,
        )
        for threshold in thresholds
    ]
    best = min(
        evaluations,
        key=lambda result: (
            float(result["total_cost"]),
            int(result["false_accepts"]),
            -float(result["threshold"]),
        ),
    )
    return {
        "selected": best,
        "candidates_evaluated": len(evaluations),
        "costs": {
            "false_accept": float(false_accept_cost),
            "false_reject": float(false_reject_cost),
        },
    }


def calibrate_sufficiency_threshold(
    benchmark_report: dict[str, Any],
    *,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
    false_accept_cost: float = DEFAULT_FALSE_ACCEPT_COST,
    false_reject_cost: float = DEFAULT_FALSE_REJECT_COST,
) -> dict[str, Any]:
    rows = [
        row
        for row in (benchmark_report.get("cases") or [])
        if isinstance(row, dict)
    ]
    calibration, holdout = deterministic_stratified_split(
        rows,
        calibration_fraction=calibration_fraction,
    )
    labels = {_label(row) for row in calibration}
    if 0 not in labels or 1 not in labels:
        raise ValueError(
            "calibration split requires both positive and selective-control cases"
        )

    selection = choose_cost_sensitive_threshold(
        calibration,
        false_accept_cost=false_accept_cost,
        false_reject_cost=false_reject_cost,
    )
    threshold = float(selection["selected"]["threshold"])
    holdout_metrics = threshold_metrics(
        holdout,
        threshold,
        false_accept_cost=false_accept_cost,
        false_reject_cost=false_reject_cost,
    )
    calibration_metrics = threshold_metrics(
        calibration,
        threshold,
        false_accept_cost=false_accept_cost,
        false_reject_cost=false_reject_cost,
    )

    return {
        "scope": "sufficiency-threshold-calibration",
        "status": "advisory_only",
        "threshold": threshold,
        "split": {
            "method": "deterministic_sha256_stratified",
            "calibration_fraction": calibration_fraction,
            "calibration_cases": len(calibration),
            "holdout_cases": len(holdout),
        },
        "costs": selection["costs"],
        "calibration": calibration_metrics,
        "holdout": holdout_metrics,
        "candidates_evaluated": selection["candidates_evaluated"],
        "warning": (
            "This calibration is not applied to runtime configuration. "
            "Agent Retrieval Bench shows that thresholds calibrated on "
            "counterfactual controls may fail to generalize to natural no-gold "
            "cases, so deployment requires representative held-out controls."
        ),
    }
