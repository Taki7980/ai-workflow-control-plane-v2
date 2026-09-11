from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contextual_features import (
    FEATURE_SCHEMA_VERSION,
    context_key,
)
from .io_utils import atomic_write_json
from .policy_manifest import verify_policy_manifest
from .retrieval_learning import BASELINE_ARM, load_learning_records


DEPLOYMENT_SCHEMA_VERSION = "retrieval-deployment-state-v1"
DEPLOYMENT_STAGES = (
    "approved",
    "canary_1",
    "canary_5",
    "canary_10",
    "bounded",
    "rolled_back",
)
LIVE_STAGES = frozenset({"canary_1", "canary_5", "canary_10", "bounded"})
STAGE_TRAFFIC = {
    "approved": 0.0,
    "canary_1": 0.01,
    "canary_5": 0.05,
    "canary_10": 0.10,
    "rolled_back": 0.0,
}
NEXT_STAGE = {
    "approved": "canary_1",
    "canary_1": "canary_5",
    "canary_5": "canary_10",
    "canary_10": "bounded",
}
DEFAULT_STAGE_EXPOSURE_BUDGETS = {
    "canary_1": 100,
    "canary_5": 500,
    "canary_10": 1000,
    "bounded": 5000,
}
DEFAULT_STAGE_FAILURE_BUDGETS = {
    "canary_1": 5,
    "canary_5": 20,
    "canary_10": 40,
    "bounded": 100,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _key_id(signing_key: bytes) -> str:
    return hashlib.sha256(signing_key).hexdigest()[:16]


def _sign_payload(payload: dict[str, Any], signing_key: bytes) -> dict[str, Any]:
    if not signing_key:
        raise ValueError("signing key must not be empty")
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    signature = hmac.new(
        signing_key,
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    signed = dict(unsigned)
    signed["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": _key_id(signing_key),
        "value": signature,
    }
    return signed


def _verify_signature(
    payload: dict[str, Any],
    signing_key: bytes,
) -> list[str]:
    errors: list[str] = []
    signature = payload.get("signature")
    if not signing_key:
        return ["signing_key_missing"]
    if not isinstance(signature, dict):
        return ["signature_missing"]
    if signature.get("algorithm") != "hmac-sha256":
        errors.append("signature_algorithm_mismatch")
    if signature.get("key_id") != _key_id(signing_key):
        errors.append("key_id_mismatch")
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    expected = hmac.new(
        signing_key,
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    supplied = str(signature.get("value", ""))
    if not hmac.compare_digest(expected, supplied):
        errors.append("signature_mismatch")
    return errors


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _traffic_for_stage(state: dict[str, Any], stage: str) -> float:
    if stage == "bounded":
        value = state.get("bounded_traffic_fraction", 0.25)
        return float(value)
    return float(STAGE_TRAFFIC.get(stage, 0.0))


def _low_risk_context_distribution(
    root: Path,
    manifest: dict[str, Any],
    *,
    limit: int = 2000,
) -> dict[str, Any]:
    fields_raw = manifest.get("context_fields")
    if not isinstance(fields_raw, list):
        raise ValueError("manifest is missing context fields")
    fields = tuple(str(field) for field in fields_raw)
    counts: dict[str, int] = {}
    accepted = 0
    rows = load_learning_records(root)[-max(1, int(limit)) :]
    for row in rows:
        if str(row.get("risk", "")).lower() != "low":
            continue
        if row.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            continue
        features = row.get("context_features")
        if not isinstance(features, dict):
            continue
        try:
            key = context_key(features, fields)
        except ValueError:
            continue
        counts[key] = counts.get(key, 0) + 1
        accepted += 1
    distribution = {
        key: count / accepted
        for key, count in counts.items()
        if accepted
    }
    return {
        "sample_size": accepted,
        "counts": dict(sorted(counts.items())),
        "distribution": {
            key: round(value, 12)
            for key, value in sorted(distribution.items())
        },
    }


def _stage_budgets(
    max_cumulative_realized_cost: float | None,
) -> dict[str, dict[str, Any]]:
    budgets: dict[str, dict[str, Any]] = {}
    for stage in LIVE_STAGES:
        budgets[stage] = {
            "max_candidate_exposures": DEFAULT_STAGE_EXPOSURE_BUDGETS[stage],
            "max_candidate_failures": DEFAULT_STAGE_FAILURE_BUDGETS[stage],
            "max_cumulative_realized_cost": max_cumulative_realized_cost,
        }
    return budgets


def create_deployment_state(
    root: Path,
    manifest: dict[str, Any],
    shadow_report: dict[str, Any],
    signing_key: bytes,
    *,
    approved_by: str,
    bounded_traffic_fraction: float = 0.25,
    reward_min: float = 0.0,
    reward_max: float = 1.0,
    max_importance_weight: float = 100.0,
    minimum_monitor_outcomes: int = 20,
    promotion_margin: float = 0.0,
    max_reward_regression: float = 0.05,
    max_failure_rate: float = 0.10,
    max_context_tv_distance: float = 0.30,
    max_unknown_context_rate: float = 0.20,
    minimum_drift_samples: int = 50,
    drift_window: int = 200,
    max_cumulative_realized_cost: float | None = None,
) -> dict[str, Any]:
    manifest_check = verify_policy_manifest(manifest, signing_key)
    if not manifest_check["valid"]:
        raise ValueError("policy manifest verification failed")
    shadow_gate = shadow_report.get("shadow_gate")
    shadow_manifest_check = shadow_report.get("manifest_verification")
    shadow_execution = shadow_report.get("execution")
    if (
        shadow_report.get("policy_id") != manifest.get("policy_id")
        or shadow_report.get("evidence_cutoff")
        != manifest.get("evidence_cutoff")
        or not isinstance(shadow_gate, dict)
        or not bool(shadow_gate.get("eligible_for_manual_promotion_review"))
        or not isinstance(shadow_manifest_check, dict)
        or not bool(shadow_manifest_check.get("valid"))
        or not isinstance(shadow_execution, dict)
        or bool(shadow_execution.get("policy_received_runtime_traffic"))
    ):
        raise ValueError(
            "shadow report is not eligible for deployment approval"
        )
    approver = str(approved_by).strip()
    if not approver:
        raise ValueError("approved_by must not be blank")
    bounded = float(bounded_traffic_fraction)
    if not math.isfinite(bounded) or not 0.10 < bounded <= 0.25:
        raise ValueError(
            "bounded_traffic_fraction must be greater than 0.10 and at most 0.25"
        )
    if not math.isfinite(reward_min) or not math.isfinite(reward_max):
        raise ValueError("reward bounds must be finite")
    if reward_max <= reward_min:
        raise ValueError("reward_max must be greater than reward_min")
    if max_importance_weight < 100.0:
        raise ValueError(
            "max_importance_weight must be at least 100 for the 1% canary"
        )
    if not 0.0 <= max_failure_rate <= 1.0:
        raise ValueError("max_failure_rate must be between 0 and 1")
    if not 0.0 <= max_context_tv_distance <= 1.0:
        raise ValueError("max_context_tv_distance must be between 0 and 1")
    if not 0.0 <= max_unknown_context_rate <= 1.0:
        raise ValueError("max_unknown_context_rate must be between 0 and 1")
    if max_cumulative_realized_cost is not None:
        if (
            not math.isfinite(max_cumulative_realized_cost)
            or max_cumulative_realized_cost < 0
        ):
            raise ValueError(
                "max_cumulative_realized_cost must be finite/non-negative"
            )

    policy_id = str(manifest.get("policy_id", "")).strip()
    now = _utc_now()
    baseline_distribution = _low_risk_context_distribution(root, manifest)
    state: dict[str, Any] = {
        "schema_version": DEPLOYMENT_SCHEMA_VERSION,
        "policy_id": policy_id,
        "stage": "approved",
        "traffic_fraction": 0.0,
        "bounded_traffic_fraction": bounded,
        "generation": 1,
        "created_at": now,
        "updated_at": now,
        "approved_by": approver,
        "automatic_runtime_activation": False,
        "policy_manifest": manifest,
        "shadow_report_sha256": _sha256_json(shadow_report),
        "baseline_context_distribution": baseline_distribution,
        "guardrails": {
            "reward_min": float(reward_min),
            "reward_max": float(reward_max),
            "max_importance_weight": float(max_importance_weight),
            "minimum_monitor_outcomes": max(1, int(minimum_monitor_outcomes)),
            "promotion_margin": float(promotion_margin),
            "max_reward_regression": max(0.0, float(max_reward_regression)),
            "max_failure_rate": float(max_failure_rate),
            "max_context_tv_distance": float(max_context_tv_distance),
            "max_unknown_context_rate": float(max_unknown_context_rate),
            "minimum_drift_samples": max(1, int(minimum_drift_samples)),
            "drift_window": max(1, int(drift_window)),
            "stage_budgets": _stage_budgets(max_cumulative_realized_cost),
        },
        "rollback": {
            "target_arm": BASELINE_ARM,
            "automatic": True,
            "reason": None,
            "rolled_back_at": None,
        },
        "history": [
            {
                "generation": 1,
                "from": "shadow",
                "to": "approved",
                "actor": approver,
                "at": now,
                "evidence_sha256": _sha256_json(shadow_report),
                "reason": "manual approval after signed shadow evidence",
            }
        ],
    }
    return _sign_payload(state, signing_key)


def verify_deployment_state(
    state: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    errors = _verify_signature(state, signing_key)
    if state.get("schema_version") != DEPLOYMENT_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    stage = str(state.get("stage", ""))
    if stage not in DEPLOYMENT_STAGES:
        errors.append("invalid_stage")
    generation = state.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        errors.append("invalid_generation")

    manifest = state.get("policy_manifest")
    if not isinstance(manifest, dict):
        errors.append("manifest_missing")
        manifest_check: dict[str, Any] = {"valid": False}
    else:
        manifest_check = verify_policy_manifest(manifest, signing_key)
        if not manifest_check["valid"]:
            errors.append("manifest_verification_failed")
        if state.get("policy_id") != manifest.get("policy_id"):
            errors.append("policy_id_mismatch")

    bounded = state.get("bounded_traffic_fraction")
    if (
        isinstance(bounded, bool)
        or not isinstance(bounded, (int, float))
        or not 0.10 < float(bounded) <= 0.25
    ):
        errors.append("invalid_bounded_traffic_fraction")
    expected_traffic = (
        _traffic_for_stage(state, stage)
        if stage in DEPLOYMENT_STAGES
        else None
    )
    actual_traffic = state.get("traffic_fraction")
    if (
        expected_traffic is None
        or isinstance(actual_traffic, bool)
        or not isinstance(actual_traffic, (int, float))
        or abs(float(actual_traffic) - expected_traffic) > 1e-12
    ):
        errors.append("traffic_fraction_mismatch")

    if bool(state.get("automatic_runtime_activation")):
        errors.append("automatic_activation_forbidden")
    rollback = state.get("rollback")
    if (
        not isinstance(rollback, dict)
        or rollback.get("target_arm") != BASELINE_ARM
    ):
        errors.append("rollback_target_mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "policy_id": state.get("policy_id"),
        "stage": stage,
        "generation": generation,
        "traffic_fraction": actual_traffic,
        "manifest_verification": manifest_check,
        "automatic_runtime_activation": False,
        "rollback_target": BASELINE_ARM,
    }


def transition_deployment_state(
    state: dict[str, Any],
    signing_key: bytes,
    *,
    to_stage: str,
    actor: str,
    guardrail_report: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    verification = verify_deployment_state(state, signing_key)
    if not verification["valid"]:
        raise ValueError("deployment state verification failed")
    current = str(state["stage"])
    target = str(to_stage).strip()
    actor_value = str(actor).strip()
    if not actor_value:
        raise ValueError("actor must not be blank")
    if target == "rolled_back":
        if current == "rolled_back":
            raise ValueError("deployment is already rolled back")
    else:
        expected = NEXT_STAGE.get(current)
        if expected != target:
            raise ValueError(
                f"invalid deployment transition: {current} -> {target}"
            )
        if current in LIVE_STAGES:
            if not isinstance(guardrail_report, dict):
                raise ValueError(
                    "live-stage promotion requires a passing guardrail report"
                )
            gate = guardrail_report.get("gate")
            if (
                not isinstance(gate, dict)
                or not bool(gate.get("safe_to_advance"))
            ):
                raise ValueError(
                    "live-stage promotion requires a passing guardrail report"
                )
            if guardrail_report.get("policy_id") != state.get("policy_id"):
                raise ValueError("guardrail report policy_id mismatch")
            if guardrail_report.get("state_generation") != state.get(
                "generation"
            ):
                raise ValueError("guardrail report generation mismatch")
            if guardrail_report.get("stage") != current:
                raise ValueError("guardrail report stage mismatch")

    unsigned = dict(state)
    unsigned.pop("signature", None)
    now = _utc_now()
    generation = int(state["generation"]) + 1
    unsigned["stage"] = target
    unsigned["traffic_fraction"] = _traffic_for_stage(unsigned, target)
    unsigned["generation"] = generation
    unsigned["updated_at"] = now
    history = list(unsigned.get("history") or [])
    history.append(
        {
            "generation": generation,
            "from": current,
            "to": target,
            "actor": actor_value,
            "at": now,
            "evidence_sha256": (
                _sha256_json(guardrail_report)
                if guardrail_report is not None
                else None
            ),
            "reason": (
                str(reason).strip()
                if reason is not None and str(reason).strip()
                else (
                    "manual staged promotion"
                    if target != "rolled_back"
                    else "manual or automatic rollback"
                )
            ),
        }
    )
    unsigned["history"] = history
    if target == "rolled_back":
        rollback = dict(unsigned.get("rollback") or {})
        rollback["reason"] = (
            str(reason).strip()
            if reason is not None and str(reason).strip()
            else "deployment guardrail rollback"
        )
        rollback["rolled_back_at"] = now
        rollback["automatic"] = actor_value.startswith("runtime:")
        unsigned["rollback"] = rollback
    return _sign_payload(unsigned, signing_key)


def load_deployment_state(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("deployment state must be a JSON object")
    return data


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    lock = path.with_name(path.name + ".lock")
    try:
        lock.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError(
            f"deployment state is locked: {lock}"
        ) from exc
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def _write_audit_event(path: Path, state: dict[str, Any]) -> None:
    events = path.parent / "events"
    events.mkdir(parents=True, exist_ok=True)
    policy_id = str(state.get("policy_id", "unknown"))
    generation = int(state.get("generation", 0))
    stage = str(state.get("stage", "unknown"))
    event_path = events / (
        f"{generation:06d}-{policy_id[:12]}-{stage}.json"
    )
    raw = json.dumps(
        {
            "policy_id": policy_id,
            "generation": generation,
            "stage": stage,
            "updated_at": state.get("updated_at"),
            "state_sha256": _sha256_json(state),
            "history_tail": (
                (state.get("history") or [])[-1]
                if isinstance(state.get("history"), list)
                else None
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(event_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def write_new_deployment_state(
    path: Path,
    state: dict[str, Any],
    signing_key: bytes,
) -> str:
    verification = verify_deployment_state(state, signing_key)
    if not verification["valid"]:
        raise ValueError("refusing to write invalid deployment state")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _state_lock(path):
        if path.exists():
            raise FileExistsError(
                f"deployment state already exists: {path}"
            )
        atomic_write_json(path, state, sort_keys=True)
        _write_audit_event(path, state)
    return path.as_posix()


def update_deployment_state_file(
    path: Path,
    signing_key: bytes,
    *,
    to_stage: str,
    actor: str,
    expected_generation: int | None = None,
    guardrail_report: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    with _state_lock(path):
        current = load_deployment_state(path)
        verification = verify_deployment_state(current, signing_key)
        if not verification["valid"]:
            raise ValueError("deployment state verification failed")
        if (
            expected_generation is not None
            and int(current["generation"]) != int(expected_generation)
        ):
            raise ValueError(
                "deployment state generation changed; refresh before retrying"
            )
        updated = transition_deployment_state(
            current,
            signing_key,
            to_stage=to_stage,
            actor=actor,
            guardrail_report=guardrail_report,
            reason=reason,
        )
        atomic_write_json(path, updated, sort_keys=True)
        try:
            _write_audit_event(path, updated)
        except FileExistsError:
            pass
        return updated
