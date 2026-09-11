from __future__ import annotations

import math
from typing import Any

from .contextual_features import context_key
from .deployment_state import LIVE_STAGES, verify_deployment_state
from .retrieval_learning import BASELINE_ARM, load_learning_records
from .shadow_policy import anytime_hoeffding_sequence


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _deployment_rows(
    root,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    policy_id = str(state.get("policy_id", ""))
    generation = int(state.get("generation", 0))
    rows: list[dict[str, Any]] = []
    for row in load_learning_records(root):
        deployment = row.get("deployment")
        if not isinstance(deployment, dict):
            continue
        if deployment.get("policy_id") != policy_id:
            continue
        row_generation = deployment.get("state_generation")
        if (
            isinstance(row_generation, bool)
            or not isinstance(row_generation, int)
            or row_generation > generation
        ):
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("created_at", "")))
    return rows


def _context_distribution(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> tuple[dict[str, float], int, int]:
    counts: dict[str, int] = {}
    total = 0
    invalid = 0
    for row in rows:
        features = row.get("context_features")
        if not isinstance(features, dict):
            invalid += 1
            continue
        try:
            key = context_key(features, fields)
        except ValueError:
            invalid += 1
            continue
        counts[key] = counts.get(key, 0) + 1
        total += 1
    if not total:
        return {}, 0, invalid
    return (
        {
            key: count / total
            for key, count in counts.items()
        },
        total,
        invalid,
    )


def total_variation_distance(
    left: dict[str, float],
    right: dict[str, float],
) -> float:
    keys = set(left) | set(right)
    return 0.5 * sum(
        abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0)))
        for key in keys
    )


def _sequential_scores(
    rows: list[dict[str, Any]],
    *,
    reward_min: float,
    reward_max: float,
    max_importance_weight: float,
) -> tuple[list[float], dict[str, int]]:
    values: list[float] = []
    violations = {
        "invalid_assignment_probability": 0,
        "invalid_outcome": 0,
        "reward_range_violation": 0,
        "importance_weight_violation": 0,
    }
    for row in rows:
        deployment = row.get("deployment")
        outcome = row.get("outcome")
        if (
            not isinstance(deployment, dict)
            or not isinstance(outcome, dict)
            or not bool(outcome.get("verified"))
        ):
            continue
        assignment = str(deployment.get("assignment", ""))
        if assignment not in {"candidate", "control"}:
            continue
        probability = _number(deployment.get("candidate_probability"))
        if probability is None or not 0.0 < probability < 1.0:
            violations["invalid_assignment_probability"] += 1
            continue
        reward = _number(outcome.get("reward"))
        if reward is None:
            violations["invalid_outcome"] += 1
            continue
        if reward < reward_min or reward > reward_max:
            violations["reward_range_violation"] += 1
            continue

        if assignment == "candidate":
            weight = 1.0 / probability
            score = weight * reward
        else:
            weight = 1.0 / (1.0 - probability)
            score = -weight * reward
        if weight > max_importance_weight:
            violations["importance_weight_violation"] += 1
            continue
        values.append(score)
    return values, violations


def evaluate_live_guardrails(
    root,
    state: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    verification = verify_deployment_state(state, signing_key)
    stage = str(state.get("stage", ""))
    policy_id = str(state.get("policy_id", ""))
    generation = state.get("generation")
    if not verification["valid"]:
        return {
            "scope": "live-deployment-guardrails",
            "policy_id": policy_id,
            "stage": stage,
            "state_generation": generation,
            "state_verification": verification,
            "gate": {
                "rollback_required": True,
                "safe_to_advance": False,
                "blockers": ["deployment_state_verification_failed"],
            },
        }

    guardrails = state.get("guardrails")
    if not isinstance(guardrails, dict):
        raise ValueError("deployment state is missing guardrails")
    manifest = state.get("policy_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("deployment state is missing policy manifest")
    fields_raw = manifest.get("context_fields")
    policy = manifest.get("policy")
    if not isinstance(fields_raw, list) or not isinstance(policy, dict):
        raise ValueError("deployment manifest is missing context policy")
    fields = tuple(str(field) for field in fields_raw)

    rows = _deployment_rows(root, state)
    live_rows = [
        row
        for row in rows
        if isinstance(row.get("deployment"), dict)
        and row["deployment"].get("stage") in LIVE_STAGES
    ]
    candidate_rows = [
        row
        for row in live_rows
        if row["deployment"].get("assignment") == "candidate"
    ]
    control_rows = [
        row
        for row in live_rows
        if row["deployment"].get("assignment") == "control"
    ]
    candidate_outcomes = [
        row
        for row in candidate_rows
        if isinstance(row.get("outcome"), dict)
        and bool(row["outcome"].get("verified"))
    ]
    control_outcomes = [
        row
        for row in control_rows
        if isinstance(row.get("outcome"), dict)
        and bool(row["outcome"].get("verified"))
    ]

    candidate_failures = sum(
        not bool(row["outcome"].get("success"))
        for row in candidate_outcomes
    )
    candidate_costs = [
        value
        for row in candidate_outcomes
        if (value := _number(row["outcome"].get("realized_cost")))
        is not None
    ]
    cumulative_candidate_cost = sum(candidate_costs)
    failure_rate = (
        candidate_failures / len(candidate_outcomes)
        if candidate_outcomes
        else None
    )

    reward_min = float(guardrails.get("reward_min", 0.0))
    reward_max = float(guardrails.get("reward_max", 1.0))
    max_weight = float(guardrails.get("max_importance_weight", 100.0))
    scores, monitoring_violations = _sequential_scores(
        live_rows,
        reward_min=reward_min,
        reward_max=reward_max,
        max_importance_weight=max_weight,
    )
    absolute_bound = max(
        1e-12,
        max_weight * max(abs(reward_min), abs(reward_max)),
    )
    sequence = anytime_hoeffding_sequence(
        scores,
        confidence=0.95,
        absolute_bound=absolute_bound,
    )
    final = sequence.get("final")
    lower = (
        _number(final.get("lower"))
        if isinstance(final, dict)
        else None
    )
    upper = (
        _number(final.get("upper"))
        if isinstance(final, dict)
        else None
    )

    drift_window = max(1, int(guardrails.get("drift_window", 200)))
    recent = live_rows[-drift_window:]
    current_distribution, drift_samples, invalid_contexts = (
        _context_distribution(recent, fields)
    )
    baseline_payload = state.get("baseline_context_distribution")
    baseline_distribution = (
        baseline_payload.get("distribution")
        if isinstance(baseline_payload, dict)
        else {}
    )
    if not isinstance(baseline_distribution, dict):
        baseline_distribution = {}
    tv_distance = total_variation_distance(
        current_distribution,
        {
            str(key): float(value)
            for key, value in baseline_distribution.items()
            if _number(value) is not None
        },
    )
    known_contexts = {str(key) for key in policy}
    unknown = sum(
        probability
        for key, probability in current_distribution.items()
        if key not in known_contexts
    )

    stage_budgets = guardrails.get("stage_budgets")
    stage_budget = (
        stage_budgets.get(stage)
        if isinstance(stage_budgets, dict)
        else None
    )
    if not isinstance(stage_budget, dict):
        stage_budget = {}
    max_exposures = int(
        stage_budget.get("max_candidate_exposures", 0)
    )
    max_failures = int(
        stage_budget.get("max_candidate_failures", 0)
    )
    max_cost = _number(
        stage_budget.get("max_cumulative_realized_cost")
    )

    blockers: list[str] = []
    rollback_blockers: list[str] = []
    if stage not in LIVE_STAGES:
        blockers.append("stage_not_live")
    if max_exposures > 0 and len(candidate_rows) > max_exposures:
        rollback_blockers.append("candidate_exposure_budget_exhausted")
    if max_failures >= 0 and candidate_failures > max_failures:
        rollback_blockers.append("candidate_failure_budget_exhausted")
    if max_cost is not None and cumulative_candidate_cost > max_cost:
        rollback_blockers.append("candidate_cost_budget_exhausted")

    minimum_monitor = max(
        1,
        int(guardrails.get("minimum_monitor_outcomes", 20)),
    )
    monitored_outcomes = len(candidate_outcomes) + len(control_outcomes)
    max_failure_rate = float(guardrails.get("max_failure_rate", 0.10))
    if (
        len(candidate_outcomes) >= minimum_monitor
        and failure_rate is not None
        and failure_rate > max_failure_rate
    ):
        rollback_blockers.append("candidate_failure_rate_regression")

    regression_margin = max(
        0.0,
        float(guardrails.get("max_reward_regression", 0.05)),
    )
    if (
        monitored_outcomes >= minimum_monitor
        and upper is not None
        and upper < -regression_margin
    ):
        rollback_blockers.append("reward_regression_confident")

    minimum_drift = max(
        1,
        int(guardrails.get("minimum_drift_samples", 50)),
    )
    if drift_samples >= minimum_drift:
        max_tv = float(
            guardrails.get("max_context_tv_distance", 0.30)
        )
        max_unknown = float(
            guardrails.get("max_unknown_context_rate", 0.20)
        )
        if tv_distance > max_tv:
            rollback_blockers.append("context_distribution_drift")
        if unknown > max_unknown:
            rollback_blockers.append("unknown_context_rate_exceeded")

    if invalid_contexts:
        rollback_blockers.append("invalid_context_features")
    if any(monitoring_violations.values()):
        rollback_blockers.append("monitoring_input_violation")

    blockers.extend(rollback_blockers)
    if len(candidate_outcomes) < minimum_monitor:
        blockers.append("insufficient_candidate_monitor_outcomes")
    promotion_margin = float(guardrails.get("promotion_margin", 0.0))
    evidence_of_improvement = (
        lower is not None and lower > promotion_margin
    )

    return {
        "scope": "live-deployment-guardrails",
        "policy_id": policy_id,
        "stage": stage,
        "state_generation": int(state["generation"]),
        "state_verification": verification,
        "traffic_fraction": state.get("traffic_fraction"),
        "exposure": {
            "candidate": len(candidate_rows),
            "control": len(control_rows),
            "candidate_verified_outcomes": len(candidate_outcomes),
            "control_verified_outcomes": len(control_outcomes),
            "candidate_failures": candidate_failures,
            "candidate_failure_rate": (
                round(failure_rate, 6)
                if failure_rate is not None
                else None
            ),
            "cumulative_candidate_realized_cost": round(
                cumulative_candidate_cost,
                6,
            ),
        },
        "sequential_reward_difference": sequence,
        "monitoring_violations": monitoring_violations,
        "drift": {
            "window": drift_window,
            "samples": drift_samples,
            "invalid_contexts": invalid_contexts,
            "total_variation_distance": round(tv_distance, 6),
            "unknown_context_rate": round(unknown, 6),
        },
        "current_stage_budget": stage_budget,
        "gate": {
            "rollback_required": bool(rollback_blockers),
            "safe_to_advance": not blockers,
            "rollback_blockers": rollback_blockers,
            "blockers": list(dict.fromkeys(blockers)),
            "minimum_monitor_outcomes": minimum_monitor,
            "promotion_margin": promotion_margin,
            "evidence_of_improvement": evidence_of_improvement,
            "advance_rule": (
                "minimum candidate outcomes plus no live rollback blocker"
            ),
            "max_reward_regression": regression_margin,
        },
        "automatic_runtime_activation": False,
        "rollback_target": BASELINE_ARM,
    }
