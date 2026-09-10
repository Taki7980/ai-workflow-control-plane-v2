from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .contextual_features import (
    FEATURE_SCHEMA_VERSION,
    context_key,
    normalize_context_features,
)
from .contextual_policy import evaluate_context_policy_dr
from .policy_manifest import verify_policy_manifest
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


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _verified_post_cutoff_rows(
    root,
    cutoff: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cutoff_time = _parse_timestamp(cutoff)
    if cutoff_time is None:
        raise ValueError("manifest evidence cutoff is not a valid timestamp")

    accepted: list[dict[str, Any]] = []
    excluded = {
        "not_after_cutoff": 0,
        "unverified": 0,
        "invalid_outcome": 0,
        "feature_schema_mismatch": 0,
        "invalid_propensity": 0,
        "invalid_timestamp": 0,
    }
    for row in load_learning_records(root):
        outcome = row.get("outcome")
        if not isinstance(outcome, dict) or not bool(outcome.get("verified")):
            excluded["unverified"] += 1
            continue
        recorded_at = _parse_timestamp(outcome.get("recorded_at"))
        if recorded_at is None:
            excluded["invalid_timestamp"] += 1
            continue
        if recorded_at <= cutoff_time:
            excluded["not_after_cutoff"] += 1
            continue
        reward = _number(outcome.get("reward"))
        cost = _number(outcome.get("realized_cost"))
        if reward is None or cost is None or cost < 0:
            excluded["invalid_outcome"] += 1
            continue
        if row.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            excluded["feature_schema_mismatch"] += 1
            continue
        features = normalize_context_features(row.get("context_features"))
        if features is None:
            excluded["feature_schema_mismatch"] += 1
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

    accepted.sort(
        key=lambda row: str(
            (row.get("outcome") or {}).get("recorded_at", "")
        )
    )
    return accepted, excluded


def desired_manifest_action(
    row: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    if str(row.get("risk", "")).lower() != "low":
        return BASELINE_ARM
    fields_raw = manifest.get("context_fields")
    policy = manifest.get("policy")
    if not isinstance(fields_raw, list) or not isinstance(policy, dict):
        return BASELINE_ARM
    features = row.get("context_features")
    if not isinstance(features, dict):
        return BASELINE_ARM
    key = context_key(features, tuple(str(x) for x in fields_raw))
    arm = str(policy.get(key, BASELINE_ARM))
    return arm if arm in SAFE_EXPLORATION_ARMS else BASELINE_ARM


def _supported_for_target(
    row: dict[str, Any],
    target: str,
) -> bool:
    propensities = row.get("arm_propensities")
    if not isinstance(propensities, dict):
        return False
    probability = _number(propensities.get(target))
    return probability is not None and probability > 0


def _sequential_reward_score(
    row: dict[str, Any],
    target: str,
    *,
    reward_min: float,
    reward_max: float,
    max_importance_weight: float,
) -> tuple[float | None, str | None]:
    outcome = row.get("outcome")
    if not isinstance(outcome, dict):
        return None, "invalid_outcome"
    reward = _number(outcome.get("reward"))
    if reward is None or reward < reward_min or reward > reward_max:
        return None, "reward_range_violation"

    chosen = str(row.get("chosen_arm", "")).strip()
    propensities = row.get("arm_propensities")
    if not isinstance(propensities, dict):
        return None, "invalid_propensity"
    probability = _number(propensities.get(chosen))
    if probability is None or probability <= 0:
        return None, "invalid_propensity"

    target_term = 0.0
    baseline_term = 0.0
    if chosen == target:
        weight = 1.0 / probability
        if weight > max_importance_weight:
            return None, "importance_weight_violation"
        target_term = weight * reward
    if chosen == BASELINE_ARM:
        weight = 1.0 / probability
        if weight > max_importance_weight:
            return None, "importance_weight_violation"
        baseline_term = weight * reward
    return target_term - baseline_term, None


def anytime_hoeffding_sequence(
    values: list[float],
    *,
    confidence: float,
    absolute_bound: float,
) -> dict[str, Any]:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if absolute_bound <= 0 or not math.isfinite(absolute_bound):
        raise ValueError("absolute_bound must be finite and positive")

    alpha = 1.0 - confidence
    running = 0.0
    checkpoints: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    for index, value in enumerate(values, start=1):
        running += value
        mean = running / index
        allocated_alpha = alpha * 6.0 / (math.pi**2 * index**2)
        radius = absolute_bound * math.sqrt(
            2.0 * math.log(2.0 / allocated_alpha) / index
        )
        current = {
            "n": index,
            "mean": round(mean, 6),
            "lower": round(mean - radius, 6),
            "upper": round(mean + radius, 6),
        }
        final = current
        if index & (index - 1) == 0:
            checkpoints.append(current)

    if final is not None:
        if not checkpoints or checkpoints[-1]["n"] != final["n"]:
            checkpoints.append(final)

    return {
        "confidence": confidence,
        "method": "union_bound_hoeffding_anytime_sequence",
        "anytime_valid": True,
        "exact_off_policy_confidence_sequence_paper": False,
        "absolute_bound": absolute_bound,
        "final": final,
        "checkpoints": checkpoints,
    }


def evaluate_shadow_policy(
    root,
    manifest: dict[str, Any],
    signing_key: bytes,
    *,
    confidence: float = 0.95,
    reward_min: float = 0.0,
    reward_max: float = 1.0,
    max_importance_weight: float = 20.0,
    minimum_new_events: int = 20,
    safety_margin: float = 0.0,
    max_realized_cost: float | None = None,
    bootstrap_resamples: int = 5000,
    bootstrap_seed: int = 20260911,
) -> dict[str, Any]:
    verification = verify_policy_manifest(manifest, signing_key)
    if reward_max <= reward_min:
        raise ValueError("reward_max must be greater than reward_min")
    if max_importance_weight <= 0:
        raise ValueError("max_importance_weight must be positive")

    cutoff = str(manifest.get("evidence_cutoff", "")).strip()
    rows, excluded = _verified_post_cutoff_rows(root, cutoff)
    fields_raw = manifest.get("context_fields")
    policy = manifest.get("policy")
    reward_model = manifest.get("reward_model")
    cost_model = manifest.get("cost_model")
    if (
        not isinstance(fields_raw, list)
        or not isinstance(policy, dict)
        or not isinstance(reward_model, dict)
        or not isinstance(cost_model, dict)
    ):
        raise ValueError("manifest is missing contextual policy evidence")
    fields = tuple(str(field) for field in fields_raw)

    supported_rows: list[dict[str, Any]] = []
    unsupported_target_events = 0
    scores: list[float] = []
    violations = {
        "reward_range_violation": 0,
        "importance_weight_violation": 0,
        "invalid_outcome": 0,
        "invalid_propensity": 0,
    }
    direct_target_costs: list[float] = []

    for row in rows:
        target = desired_manifest_action(row, manifest)
        if not _supported_for_target(row, target):
            unsupported_target_events += 1
            continue
        score, error = _sequential_reward_score(
            row,
            target,
            reward_min=reward_min,
            reward_max=reward_max,
            max_importance_weight=max_importance_weight,
        )
        if error is not None:
            violations[error] = violations.get(error, 0) + 1
            continue
        if score is None:
            continue
        supported_rows.append(row)
        scores.append(score)

        chosen = str(row.get("chosen_arm", "")).strip()
        if target != BASELINE_ARM and chosen == target:
            outcome = row.get("outcome")
            cost = (
                _number(outcome.get("realized_cost"))
                if isinstance(outcome, dict)
                else None
            )
            if cost is not None:
                direct_target_costs.append(cost)

    max_abs_reward = max(abs(reward_min), abs(reward_max))
    bound = max_importance_weight * max_abs_reward
    sequence = anytime_hoeffding_sequence(
        scores,
        confidence=confidence,
        absolute_bound=max(bound, 1e-12),
    )
    dr = evaluate_context_policy_dr(
        supported_rows,
        {str(k): str(v) for k, v in policy.items()},
        reward_model,
        cost_model,
        fields,
        confidence=confidence,
        resamples=bootstrap_resamples,
        seed=bootstrap_seed,
    )

    blockers: list[str] = []
    if not verification["valid"]:
        blockers.append("manifest_verification_failed")
    if len(rows) < max(1, minimum_new_events):
        blockers.append("insufficient_post_cutoff_events")
    if unsupported_target_events:
        blockers.append("target_policy_support_violation")
    if any(violations.values()):
        blockers.append("sequential_monitoring_input_violation")
    final = sequence.get("final")
    lower = final.get("lower") if isinstance(final, dict) else None
    if lower is None or float(lower) <= safety_margin:
        blockers.append("anytime_lower_bound_does_not_clear_margin")
    max_direct_cost = max(direct_target_costs) if direct_target_costs else None
    if max_realized_cost is not None:
        if max_direct_cost is None or max_direct_cost > max_realized_cost:
            blockers.append("realized_cost_constraint_not_met")

    return {
        "scope": "contextual-retrieval-shadow-evaluation",
        "policy_id": manifest.get("policy_id"),
        "manifest_verification": verification,
        "evidence_cutoff": cutoff,
        "post_cutoff_events": len(rows),
        "supported_events": len(supported_rows),
        "excluded_events": excluded,
        "unsupported_target_events": unsupported_target_events,
        "monitoring_violations": violations,
        "doubly_robust_shadow_evaluation": dr,
        "sequential_reward_confidence": sequence,
        "max_direct_realized_cost": (
            round(max_direct_cost, 6)
            if max_direct_cost is not None
            else None
        ),
        "shadow_gate": {
            "eligible_for_manual_promotion_review": not blockers,
            "blockers": blockers,
            "minimum_new_events": minimum_new_events,
            "safety_margin": safety_margin,
            "max_realized_cost": max_realized_cost,
            "automatic_runtime_activation": False,
        },
        "execution": {
            "policy_received_runtime_traffic": False,
            "mode": "counterfactual_shadow_only",
            "rollback_target": BASELINE_ARM,
        },
        "methodology": {
            "sequential_gate": (
                "conservative union-bound Hoeffding confidence sequence"
            ),
            "paper_equivalence": (
                "does not implement the exact betting/martingale construction "
                "from Off-policy Confidence Sequences"
            ),
        },
    }
