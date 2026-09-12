from __future__ import annotations

import math
import random
import statistics
from typing import Any

from .benchmark_statistics import percentile
from .retrieval_learning import (
    BASELINE_ARM,
    SAFE_EXPLORATION_ARMS,
    load_learning_records,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _verified_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        outcome = row.get("outcome")
        if not isinstance(outcome, dict) or not bool(outcome.get("verified")):
            continue
        reward = _number(outcome.get("reward"))
        cost = _number(outcome.get("realized_cost"))
        if reward is None or cost is None or cost < 0:
            continue
        arm_propensities = row.get("arm_propensities")
        if not isinstance(arm_propensities, dict):
            continue
        chosen = str(row.get("chosen_arm", ""))
        chosen_probability = _number(arm_propensities.get(chosen))
        if chosen_probability is None or chosen_probability <= 0:
            continue
        out.append(row)
    return out


def _safe_target_action(row: dict[str, Any], target_arm: str) -> str:
    propensities = row.get("arm_propensities")
    if not isinstance(propensities, dict):
        return BASELINE_ARM
    target_probability = _number(propensities.get(target_arm))
    return (
        target_arm
        if target_probability is not None and target_probability > 0
        else BASELINE_ARM
    )


def _estimate(
    rows: list[dict[str, Any]],
    target_arm: str,
) -> dict[str, Any]:
    weighted_rewards: list[float] = []
    weighted_costs: list[float] = []
    weights: list[float] = []
    matched = 0
    direct_target_exposures = 0
    direct_target_costs: list[float] = []

    for row in rows:
        chosen = str(row.get("chosen_arm", ""))
        target_action = _safe_target_action(row, target_arm)
        if chosen != target_action:
            continue
        propensities = row["arm_propensities"]
        probability = _number(propensities.get(chosen))
        outcome = row["outcome"]
        reward = _number(outcome.get("reward"))
        cost = _number(outcome.get("realized_cost"))
        if (
            probability is None
            or probability <= 0
            or reward is None
            or cost is None
        ):
            continue
        weight = 1.0 / probability
        matched += 1
        weights.append(weight)
        weighted_rewards.append(weight * reward)
        weighted_costs.append(weight * cost)
        if chosen == target_arm and target_arm != BASELINE_ARM:
            direct_target_exposures += 1
            direct_target_costs.append(cost)

    total_weight = sum(weights)
    n = len(rows)
    ips_reward = sum(weighted_rewards) / n if n else None
    snips_reward = (
        sum(weighted_rewards) / total_weight
        if total_weight > 0
        else None
    )
    ips_cost = sum(weighted_costs) / n if n else None
    snips_cost = (
        sum(weighted_costs) / total_weight
        if total_weight > 0
        else None
    )
    squared_weight_sum = sum(weight * weight for weight in weights)
    ess = (
        total_weight * total_weight / squared_weight_sum
        if squared_weight_sum > 0
        else 0.0
    )
    return {
        "target_arm": target_arm,
        "logged_events": n,
        "matched_events": matched,
        "direct_target_exposures": direct_target_exposures,
        "coverage": round(matched / n, 6) if n else 0.0,
        "ips_reward": round(ips_reward, 6) if ips_reward is not None else None,
        "snips_reward": (
            round(snips_reward, 6) if snips_reward is not None else None
        ),
        "ips_cost": round(ips_cost, 6) if ips_cost is not None else None,
        "snips_cost": round(snips_cost, 6) if snips_cost is not None else None,
        "effective_sample_size": round(ess, 6),
        "max_importance_weight": (
            round(max(weights), 6) if weights else None
        ),
        "max_direct_realized_cost": (
            round(max(direct_target_costs), 6)
            if direct_target_costs
            else None
        ),
    }


def _snips_value(
    rows: list[dict[str, Any]],
    target_arm: str,
    field: str,
) -> float | None:
    weighted = 0.0
    total_weight = 0.0
    for row in rows:
        chosen = str(row.get("chosen_arm", ""))
        target_action = _safe_target_action(row, target_arm)
        if chosen != target_action:
            continue
        probability = _number(row["arm_propensities"].get(chosen))
        outcome = row.get("outcome")
        value = _number(outcome.get(field)) if isinstance(outcome, dict) else None
        if probability is None or probability <= 0 or value is None:
            continue
        weight = 1.0 / probability
        weighted += weight * value
        total_weight += weight
    return weighted / total_weight if total_weight > 0 else None


def _bootstrap_delta(
    rows: list[dict[str, Any]],
    target_arm: str,
    *,
    field: str,
    confidence: float,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if not rows:
        return {
            "mean_delta": None,
            "ci_low": None,
            "ci_high": None,
            "resamples_used": 0,
        }

    rng = random.Random(int(seed))  # noqa: S311 - deterministic statistical bootstrap
    n = len(rows)
    draws = max(1, int(resamples))
    deltas: list[float] = []
    for _ in range(draws):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        candidate = _snips_value(sample, target_arm, field)
        baseline = _snips_value(sample, BASELINE_ARM, field)
        if candidate is None or baseline is None:
            continue
        deltas.append(candidate - baseline)

    observed_candidate = _snips_value(rows, target_arm, field)
    observed_baseline = _snips_value(rows, BASELINE_ARM, field)
    observed_delta = (
        observed_candidate - observed_baseline
        if observed_candidate is not None and observed_baseline is not None
        else None
    )
    if not deltas:
        return {
            "mean_delta": (
                round(observed_delta, 6)
                if observed_delta is not None
                else None
            ),
            "ci_low": None,
            "ci_high": None,
            "resamples_used": 0,
        }

    alpha = (1.0 - confidence) / 2.0
    return {
        "mean_delta": (
            round(observed_delta, 6)
            if observed_delta is not None
            else round(statistics.mean(deltas), 6)
        ),
        "ci_low": round(percentile(deltas, alpha), 6),
        "ci_high": round(percentile(deltas, 1.0 - alpha), 6),
        "resamples_used": len(deltas),
    }


def evaluate_learning_policies(
    root,
    *,
    arms: list[str] | tuple[str, ...] | None = None,
    confidence: float = 0.95,
    resamples: int = 5000,
    seed: int = 20260911,
    minimum_effective_sample_size: float = 10.0,
    minimum_direct_exposures: int = 5,
    safety_margin: float = 0.0,
    max_realized_cost: float | None = None,
) -> dict[str, Any]:
    requested = list(arms or SAFE_EXPLORATION_ARMS)
    normalized = list(dict.fromkeys(str(arm).strip() for arm in requested))
    for arm in normalized:
        if arm not in SAFE_EXPLORATION_ARMS:
            raise ValueError(f"unsupported learning arm: {arm}")
    rows = _verified_rows(load_learning_records(root))
    baseline = _estimate(rows, BASELINE_ARM)

    evaluations: dict[str, dict[str, Any]] = {}
    for arm in normalized:
        estimate = _estimate(rows, arm)
        reward_delta = _bootstrap_delta(
            rows,
            arm,
            field="reward",
            confidence=confidence,
            resamples=resamples,
            seed=seed,
        )
        cost_delta = _bootstrap_delta(
            rows,
            arm,
            field="realized_cost",
            confidence=confidence,
            resamples=resamples,
            seed=seed + 1,
        )

        reasons: list[str] = []
        eligible = arm != BASELINE_ARM
        if estimate["effective_sample_size"] < minimum_effective_sample_size:
            eligible = False
            reasons.append("insufficient_effective_sample_size")
        if estimate["direct_target_exposures"] < minimum_direct_exposures:
            eligible = False
            reasons.append("insufficient_direct_target_exposures")
        reward_ci_low = reward_delta.get("ci_low")
        if reward_ci_low is None or float(reward_ci_low) <= safety_margin:
            eligible = False
            reasons.append("reward_lower_bound_does_not_clear_margin")
        if max_realized_cost is not None:
            observed_cost = estimate.get("max_direct_realized_cost")
            if observed_cost is None or float(observed_cost) > max_realized_cost:
                eligible = False
                reasons.append("realized_cost_constraint_not_met")

        evaluations[arm] = {
            **estimate,
            "reward_delta_vs_baseline": reward_delta,
            "cost_delta_vs_baseline": cost_delta,
            "promotion_eligible": eligible,
            "promotion_blockers": reasons,
        }

    promoted = [
        (arm, data)
        for arm, data in evaluations.items()
        if data["promotion_eligible"]
    ]
    recommendation = BASELINE_ARM
    if promoted:
        recommendation = max(
            promoted,
            key=lambda item: (
                float(item[1]["reward_delta_vs_baseline"]["ci_low"]),
                float(item[1]["snips_reward"]),
                item[0],
            ),
        )[0]

    return {
        "scope": "retrieval-learning-off-policy-evaluation",
        "estimator": {
            "reward": "ips_and_snips",
            "cost": "ips_and_snips",
            "confidence_interval": "paired_nonparametric_bootstrap",
            "exact_paper_bound": False,
        },
        "logged_verified_events": len(rows),
        "baseline": baseline,
        "evaluations": evaluations,
        "promotion": {
            "recommended_arm": recommendation,
            "automatic_runtime_promotion": False,
            "minimum_effective_sample_size": minimum_effective_sample_size,
            "minimum_direct_exposures": minimum_direct_exposures,
            "safety_margin": safety_margin,
            "max_realized_cost": max_realized_cost,
        },
        "warning": (
            "SNIPS is only trustworthy when the logged behavior policy records "
            "valid propensities and provides adequate overlap. The confidence "
            "interval here is bootstrap-based and is not the exact "
            "Efron-Stein lower bound from Kuzborskij et al."
        ),
    }
