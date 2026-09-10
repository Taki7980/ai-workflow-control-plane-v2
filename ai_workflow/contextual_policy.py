from __future__ import annotations

import hashlib
import math
import statistics
from collections import defaultdict
from typing import Any

from .benchmark_statistics import bootstrap_mean_ci
from .contextual_features import (
    DEFAULT_POLICY_FIELDS,
    FEATURE_SCHEMA_VERSION,
    context_key,
    normalize_context_features,
    validate_context_fields,
)
from .retrieval_learning import (
    BASELINE_ARM,
    SAFE_EXPLORATION_ARMS,
    load_learning_records,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _verified_feature_rows(
    root,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = load_learning_records(root)
    accepted: list[dict[str, Any]] = []
    excluded = {
        "unverified": 0,
        "invalid_outcome": 0,
        "missing_current_features": 0,
        "invalid_propensity": 0,
    }
    for row in rows:
        outcome = row.get("outcome")
        if not isinstance(outcome, dict) or not bool(outcome.get("verified")):
            excluded["unverified"] += 1
            continue
        reward = _number(outcome.get("reward"))
        cost = _number(outcome.get("realized_cost"))
        if reward is None or cost is None or cost < 0:
            excluded["invalid_outcome"] += 1
            continue
        if row.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            excluded["missing_current_features"] += 1
            continue
        features = normalize_context_features(row.get("context_features"))
        if features is None:
            excluded["missing_current_features"] += 1
            continue
        propensities = row.get("arm_propensities")
        chosen = str(row.get("chosen_arm", "")).strip()
        if not isinstance(propensities, dict):
            excluded["invalid_propensity"] += 1
            continue
        probability = _number(propensities.get(chosen))
        if probability is None or probability <= 0:
            excluded["invalid_propensity"] += 1
            continue
        normalized = dict(row)
        normalized["context_features"] = features
        accepted.append(normalized)
    return accepted, excluded


def _split_rows(
    rows: list[dict[str, Any]],
    development_fraction: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fraction = float(development_fraction)
    if not 0.0 < fraction < 1.0:
        raise ValueError("development_fraction must be between 0 and 1")
    development: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    limit = int(fraction * (2**64 - 1))
    for row in rows:
        decision_id = str(row.get("decision_id", ""))
        digest = hashlib.sha256(decision_id.encode()).digest()
        bucket = int.from_bytes(digest[:8], "big")
        if bucket <= limit:
            development.append(row)
        else:
            holdout.append(row)
    return development, holdout


def _row_context(
    row: dict[str, Any],
    fields: tuple[str, ...],
) -> str:
    features = row.get("context_features")
    if not isinstance(features, dict):
        raise ValueError("learning row is missing context features")
    return context_key(features, fields)


def _outcome_value(row: dict[str, Any], field: str) -> float | None:
    outcome = row.get("outcome")
    if not isinstance(outcome, dict):
        return None
    return _number(outcome.get(field))


def fit_direct_model(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    outcome_field: str,
    prior_weight: float = 5.0,
) -> dict[str, Any]:
    if prior_weight < 0:
        raise ValueError("prior_weight must be non-negative")
    global_values: list[float] = []
    arm_values: dict[str, list[float]] = defaultdict(list)
    context_arm_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        value = _outcome_value(row, outcome_field)
        arm = str(row.get("chosen_arm", "")).strip()
        if value is None or not arm:
            continue
        key = _row_context(row, fields)
        global_values.append(value)
        arm_values[arm].append(value)
        context_arm_values[key][arm].append(value)

    global_mean = statistics.mean(global_values) if global_values else 0.0
    arm_means = {
        arm: statistics.mean(values)
        for arm, values in arm_values.items()
        if values
    }
    context_means: dict[str, dict[str, float]] = {}
    context_counts: dict[str, dict[str, int]] = {}
    for key, per_arm in context_arm_values.items():
        context_means[key] = {}
        context_counts[key] = {}
        for arm, values in per_arm.items():
            if not values:
                continue
            arm_prior = arm_means.get(arm, global_mean)
            numerator = sum(values) + prior_weight * arm_prior
            denominator = len(values) + prior_weight
            context_means[key][arm] = numerator / max(1.0, denominator)
            context_counts[key][arm] = len(values)

    return {
        "outcome_field": outcome_field,
        "context_fields": list(fields),
        "prior_weight": float(prior_weight),
        "global_mean": float(global_mean),
        "arm_means": {
            arm: float(value)
            for arm, value in sorted(arm_means.items())
        },
        "context_arm_means": {
            key: {
                arm: float(value)
                for arm, value in sorted(per_arm.items())
            }
            for key, per_arm in sorted(context_means.items())
        },
        "context_arm_counts": {
            key: dict(sorted(per_arm.items()))
            for key, per_arm in sorted(context_counts.items())
        },
    }


def predict_model_value(
    model: dict[str, Any],
    context: str,
    arm: str,
) -> float:
    by_context = model.get("context_arm_means")
    if isinstance(by_context, dict):
        values = by_context.get(context)
        if isinstance(values, dict):
            direct = _number(values.get(arm))
            if direct is not None:
                return direct
    arm_means = model.get("arm_means")
    if isinstance(arm_means, dict):
        arm_mean = _number(arm_means.get(arm))
        if arm_mean is not None:
            return arm_mean
    fallback = _number(model.get("global_mean"))
    return fallback if fallback is not None else 0.0


def cross_validate_direct_model(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    outcome_field: str,
    folds: int = 5,
    prior_weight: float = 5.0,
) -> dict[str, Any]:
    fold_count = max(2, int(folds))
    absolute_errors: list[float] = []
    squared_errors: list[float] = []
    for fold in range(fold_count):
        training: list[dict[str, Any]] = []
        validation: list[dict[str, Any]] = []
        for row in rows:
            decision_id = str(row.get("decision_id", ""))
            digest = hashlib.sha256(decision_id.encode()).digest()
            row_fold = int.from_bytes(digest[:4], "big") % fold_count
            target = validation if row_fold == fold else training
            target.append(row)
        if not training or not validation:
            continue
        model = fit_direct_model(
            training,
            fields,
            outcome_field=outcome_field,
            prior_weight=prior_weight,
        )
        for row in validation:
            observed = _outcome_value(row, outcome_field)
            if observed is None:
                continue
            arm = str(row.get("chosen_arm", "")).strip()
            predicted = predict_model_value(
                model,
                _row_context(row, fields),
                arm,
            )
            error = predicted - observed
            absolute_errors.append(abs(error))
            squared_errors.append(error * error)

    return {
        "folds": fold_count,
        "n": len(absolute_errors),
        "mae": (
            round(statistics.mean(absolute_errors), 6)
            if absolute_errors
            else None
        ),
        "rmse": (
            round(math.sqrt(statistics.mean(squared_errors)), 6)
            if squared_errors
            else None
        ),
    }


def _direct_exposures(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for row in rows:
        if str(row.get("risk", "")).lower() != "low":
            continue
        key = _row_context(row, fields)
        arm = str(row.get("chosen_arm", "")).strip()
        if arm:
            counts[key][arm] += 1
    return {
        key: dict(per_arm)
        for key, per_arm in counts.items()
    }


def build_context_policy_map(
    development_rows: list[dict[str, Any]],
    reward_model: dict[str, Any],
    fields: tuple[str, ...],
    *,
    minimum_context_events: int,
    minimum_direct_exposures: int,
    minimum_estimated_gain: float,
) -> tuple[dict[str, str], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in development_rows:
        if str(row.get("risk", "")).lower() != "low":
            continue
        groups[_row_context(row, fields)].append(row)

    exposures = _direct_exposures(development_rows, fields)
    policy: dict[str, str] = {}
    diagnostics: dict[str, Any] = {}
    for key, group in sorted(groups.items()):
        baseline_value = predict_model_value(
            reward_model,
            key,
            BASELINE_ARM,
        )
        chosen = BASELINE_ARM
        chosen_value = baseline_value
        candidates: dict[str, Any] = {}
        enough_context = len(group) >= max(1, minimum_context_events)

        for arm in SAFE_EXPLORATION_ARMS:
            direct = exposures.get(key, {}).get(arm, 0)
            estimate = predict_model_value(reward_model, key, arm)
            supported = (
                arm == BASELINE_ARM
                or direct >= max(1, minimum_direct_exposures)
            )
            candidates[arm] = {
                "direct_exposures": direct,
                "direct_model_reward": round(estimate, 6),
                "supported": supported,
            }
            if not enough_context or arm == BASELINE_ARM or not supported:
                continue
            if estimate <= baseline_value + minimum_estimated_gain:
                continue
            if estimate > chosen_value:
                chosen = arm
                chosen_value = estimate

        policy[key] = chosen
        diagnostics[key] = {
            "development_events": len(group),
            "baseline_estimated_reward": round(baseline_value, 6),
            "chosen_arm": chosen,
            "chosen_estimated_reward": round(chosen_value, 6),
            "candidates": candidates,
        }

    return policy, diagnostics


def target_action_for_row(
    row: dict[str, Any],
    policy: dict[str, str],
    fields: tuple[str, ...],
) -> str:
    if str(row.get("risk", "")).lower() != "low":
        return BASELINE_ARM
    key = _row_context(row, fields)
    requested = policy.get(key, BASELINE_ARM)
    propensities = row.get("arm_propensities")
    if not isinstance(propensities, dict):
        return BASELINE_ARM
    probability = _number(propensities.get(requested))
    return requested if probability is not None and probability > 0 else BASELINE_ARM


def _dr_value(
    row: dict[str, Any],
    target_arm: str,
    model: dict[str, Any],
    fields: tuple[str, ...],
    *,
    outcome_field: str,
) -> float | None:
    observed = _outcome_value(row, outcome_field)
    if observed is None:
        return None
    chosen = str(row.get("chosen_arm", "")).strip()
    propensities = row.get("arm_propensities")
    if not isinstance(propensities, dict):
        return None
    probability = _number(propensities.get(chosen))
    if probability is None or probability <= 0:
        return None
    key = _row_context(row, fields)
    target_prediction = predict_model_value(model, key, target_arm)
    chosen_prediction = predict_model_value(model, key, chosen)
    correction = 0.0
    if chosen == target_arm:
        correction = (observed - chosen_prediction) / probability
    return target_prediction + correction


def evaluate_context_policy_dr(
    rows: list[dict[str, Any]],
    policy: dict[str, str],
    reward_model: dict[str, Any],
    cost_model: dict[str, Any],
    fields: tuple[str, ...],
    *,
    confidence: float,
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    reward_deltas: list[float] = []
    cost_deltas: list[float] = []
    target_weights: list[float] = []
    direct_target_exposures = 0
    direct_target_costs: list[float] = []
    nonbaseline_target_events = 0

    for row in rows:
        target = target_action_for_row(row, policy, fields)
        if target != BASELINE_ARM:
            nonbaseline_target_events += 1
        target_reward = _dr_value(
            row,
            target,
            reward_model,
            fields,
            outcome_field="reward",
        )
        baseline_reward = _dr_value(
            row,
            BASELINE_ARM,
            reward_model,
            fields,
            outcome_field="reward",
        )
        target_cost = _dr_value(
            row,
            target,
            cost_model,
            fields,
            outcome_field="realized_cost",
        )
        baseline_cost = _dr_value(
            row,
            BASELINE_ARM,
            cost_model,
            fields,
            outcome_field="realized_cost",
        )
        if target_reward is not None and baseline_reward is not None:
            reward_deltas.append(target_reward - baseline_reward)
        if target_cost is not None and baseline_cost is not None:
            cost_deltas.append(target_cost - baseline_cost)

        chosen = str(row.get("chosen_arm", "")).strip()
        propensities = row.get("arm_propensities")
        probability = (
            _number(propensities.get(chosen))
            if isinstance(propensities, dict)
            else None
        )
        if chosen == target and probability is not None and probability > 0:
            target_weights.append(1.0 / probability)
            if target != BASELINE_ARM:
                direct_target_exposures += 1
                cost = _outcome_value(row, "realized_cost")
                if cost is not None:
                    direct_target_costs.append(cost)

    total_weight = sum(target_weights)
    squared = sum(weight * weight for weight in target_weights)
    ess = (
        total_weight * total_weight / squared
        if squared > 0
        else 0.0
    )
    reward_ci = bootstrap_mean_ci(
        reward_deltas,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )
    cost_ci = bootstrap_mean_ci(
        cost_deltas,
        confidence=confidence,
        resamples=resamples,
        seed=seed + 1,
    )
    return {
        "holdout_events": len(rows),
        "nonbaseline_target_events": nonbaseline_target_events,
        "direct_target_exposures": direct_target_exposures,
        "effective_sample_size": round(ess, 6),
        "max_importance_weight": (
            round(max(target_weights), 6)
            if target_weights
            else None
        ),
        "max_direct_realized_cost": (
            round(max(direct_target_costs), 6)
            if direct_target_costs
            else None
        ),
        "reward_delta_vs_baseline": reward_ci,
        "cost_delta_vs_baseline": cost_ci,
    }


def _evidence_cutoff(rows: list[dict[str, Any]]) -> str | None:
    timestamps: list[str] = []
    for row in rows:
        outcome = row.get("outcome")
        if not isinstance(outcome, dict):
            continue
        recorded = str(outcome.get("recorded_at", "")).strip()
        if recorded:
            timestamps.append(recorded)
    return max(timestamps) if timestamps else None


def _decision_digest(rows: list[dict[str, Any]]) -> str:
    identifiers = sorted(str(row.get("decision_id", "")) for row in rows)
    payload = "\n".join(identifiers).encode()
    return hashlib.sha256(payload).hexdigest()


def build_contextual_policy_report(
    root,
    *,
    context_fields: list[str] | tuple[str, ...] = DEFAULT_POLICY_FIELDS,
    development_fraction: float = 0.7,
    prior_weight: float = 5.0,
    folds: int = 5,
    minimum_context_events: int = 10,
    minimum_direct_exposures: int = 3,
    minimum_holdout_events: int = 20,
    minimum_effective_sample_size: float = 10.0,
    minimum_model_validation_events: int = 10,
    minimum_estimated_gain: float = 0.0,
    safety_margin: float = 0.0,
    max_realized_cost: float | None = None,
    confidence: float = 0.95,
    resamples: int = 5000,
    seed: int = 20260911,
) -> dict[str, Any]:
    fields = validate_context_fields(context_fields)
    rows, excluded = _verified_feature_rows(root)
    development, holdout = _split_rows(rows, development_fraction)

    reward_model = fit_direct_model(
        development,
        fields,
        outcome_field="reward",
        prior_weight=prior_weight,
    )
    cost_model = fit_direct_model(
        development,
        fields,
        outcome_field="realized_cost",
        prior_weight=prior_weight,
    )
    reward_validation = cross_validate_direct_model(
        development,
        fields,
        outcome_field="reward",
        folds=folds,
        prior_weight=prior_weight,
    )
    cost_validation = cross_validate_direct_model(
        development,
        fields,
        outcome_field="realized_cost",
        folds=folds,
        prior_weight=prior_weight,
    )
    policy, development_diagnostics = build_context_policy_map(
        development,
        reward_model,
        fields,
        minimum_context_events=minimum_context_events,
        minimum_direct_exposures=minimum_direct_exposures,
        minimum_estimated_gain=minimum_estimated_gain,
    )
    evaluation = evaluate_context_policy_dr(
        holdout,
        policy,
        reward_model,
        cost_model,
        fields,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )

    nonbaseline_contexts = sum(
        arm != BASELINE_ARM for arm in policy.values()
    )
    blockers: list[str] = []
    if nonbaseline_contexts == 0:
        blockers.append("no_contextual_candidate")
    if len(holdout) < max(1, minimum_holdout_events):
        blockers.append("insufficient_holdout_events")
    if (
        evaluation["effective_sample_size"]
        < minimum_effective_sample_size
    ):
        blockers.append("insufficient_effective_sample_size")
    if (
        evaluation["direct_target_exposures"]
        < minimum_direct_exposures
    ):
        blockers.append("insufficient_direct_target_exposures")
    if reward_validation["n"] < minimum_model_validation_events:
        blockers.append("insufficient_reward_model_validation")
    reward_low = evaluation["reward_delta_vs_baseline"]["ci_low"]
    if reward_low is None or float(reward_low) <= safety_margin:
        blockers.append("reward_lower_bound_does_not_clear_margin")
    if max_realized_cost is not None:
        observed_cost = evaluation["max_direct_realized_cost"]
        if observed_cost is None or float(observed_cost) > max_realized_cost:
            blockers.append("realized_cost_constraint_not_met")

    return {
        "scope": "contextual-retrieval-policy-development",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "context_fields": list(fields),
        "baseline_arm": BASELINE_ARM,
        "development_fraction": development_fraction,
        "development_events": len(development),
        "holdout_events": len(holdout),
        "excluded_events": excluded,
        "source_decision_sha256": _decision_digest(rows),
        "evidence_cutoff": _evidence_cutoff(rows),
        "reward_model": reward_model,
        "cost_model": cost_model,
        "reward_model_cross_validation": reward_validation,
        "cost_model_cross_validation": cost_validation,
        "development_policy": policy,
        "development_diagnostics": development_diagnostics,
        "holdout_doubly_robust_evaluation": evaluation,
        "promotion": {
            "eligible_for_shadow": not blockers,
            "automatic_runtime_promotion": False,
            "nonbaseline_contexts": nonbaseline_contexts,
            "blockers": blockers,
            "minimum_context_events": minimum_context_events,
            "minimum_direct_exposures": minimum_direct_exposures,
            "minimum_holdout_events": minimum_holdout_events,
            "minimum_effective_sample_size": (
                minimum_effective_sample_size
            ),
            "minimum_model_validation_events": (
                minimum_model_validation_events
            ),
            "minimum_estimated_gain": minimum_estimated_gain,
            "safety_margin": safety_margin,
            "max_realized_cost": max_realized_cost,
        },
        "methodology": {
            "policy_learning": (
                "development split with smoothed categorical direct model"
            ),
            "reward_model_validation": (
                "deterministic cross-validation on development rows"
            ),
            "final_evaluation": (
                "doubly robust evaluation on an untouched deterministic holdout"
            ),
            "high_risk_override": (
                "non-low-risk rows are always mapped to adaptive_math"
            ),
        },
    }
