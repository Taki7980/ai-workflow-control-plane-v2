from __future__ import annotations

import hashlib
import hmac
import math
import os
from pathlib import Path
from typing import Any

from .contextual_features import build_context_features, context_key
from .deployment_guardrails import evaluate_live_guardrails
from .deployment_state import (
    LIVE_STAGES,
    load_deployment_state,
    update_deployment_state_file,
    verify_deployment_state,
)
from .models import RouteDecision
from .retrieval_learning import BASELINE_ARM, SAFE_EXPLORATION_ARMS


def _deployment_config(config: dict[str, Any]) -> dict[str, Any]:
    context = config.get("context")
    if not isinstance(context, dict):
        return {}
    raw = context.get("deployment")
    return dict(raw) if isinstance(raw, dict) else {}


def deployment_enabled(config: dict[str, Any]) -> bool:
    return bool(_deployment_config(config).get("enabled", False))


def _state_path(root: Path, config: dict[str, Any]) -> Path:
    cfg = _deployment_config(config)
    raw = str(
        cfg.get(
            "state_path",
            "ai-workspace/generated/learning/deployment/active.json",
        )
    ).strip()
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("context.deployment.state_path must be relative")
    resolved = (root.resolve() / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(
            "context.deployment.state_path must stay inside project root"
        )
    return resolved


def _signing_key(config: dict[str, Any]) -> bytes:
    cfg = _deployment_config(config)
    env_name = str(
        cfg.get(
            "signing_key_env",
            "AI_WORKFLOW_POLICY_SIGNING_KEY",
        )
    ).strip()
    if not env_name:
        return b""
    return os.getenv(env_name, "").encode()


def _baseline_assignment(
    reason: str,
    *,
    state: dict[str, Any] | None = None,
    context: str | None = None,
    target_arm: str | None = None,
) -> dict[str, Any]:
    deployment: dict[str, Any] = {
        "assignment": "baseline",
        "reason": reason,
        "policy_id": state.get("policy_id") if state else None,
        "state_generation": state.get("generation") if state else None,
        "stage": state.get("stage") if state else None,
        "traffic_fraction": (
            state.get("traffic_fraction") if state else 0.0
        ),
        "candidate_probability": 0.0,
        "chosen_probability": 1.0,
        "target_arm": target_arm or BASELINE_ARM,
        "context_key": context,
        "source": "stage7_deployment",
    }
    return {
        "chosen_arm": BASELINE_ARM,
        "arm_propensities": {BASELINE_ARM: 1.0},
        "mode": "canary",
        "safety_reason": reason,
        "deployment": deployment,
    }


def _assignment_fraction(
    signing_key: bytes,
    policy_id: str,
    task_fingerprint: str,
) -> float:
    digest = hmac.new(
        signing_key,
        f"{policy_id}:{task_fingerprint}".encode(),
        hashlib.sha256,
    ).digest()
    numerator = int.from_bytes(digest[:8], "big")
    return numerator / float(2**64)


def _target_arm(
    state: dict[str, Any],
    features: dict[str, str],
) -> tuple[str, str | None]:
    manifest = state.get("policy_manifest")
    if not isinstance(manifest, dict):
        return BASELINE_ARM, None
    fields_raw = manifest.get("context_fields")
    policy = manifest.get("policy")
    if not isinstance(fields_raw, list) or not isinstance(policy, dict):
        return BASELINE_ARM, None
    try:
        key = context_key(
            features,
            tuple(str(field) for field in fields_raw),
        )
    except ValueError:
        return BASELINE_ARM, None
    arm = str(policy.get(key, BASELINE_ARM)).strip()
    if arm not in SAFE_EXPLORATION_ARMS:
        return BASELINE_ARM, key
    return arm, key


def _auto_rollback_if_needed(
    root: Path,
    path: Path,
    state: dict[str, Any],
    signing_key: bytes,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = _deployment_config(config)
    if (
        state.get("stage") not in LIVE_STAGES
        or not bool(cfg.get("auto_rollback", True))
    ):
        return state, None

    report = evaluate_live_guardrails(root, state, signing_key)
    gate = report.get("gate")
    if not isinstance(gate, dict) or not bool(
        gate.get("rollback_required")
    ):
        return state, report

    blockers = gate.get("rollback_blockers")
    reason = (
        ", ".join(str(value) for value in blockers)
        if isinstance(blockers, list) and blockers
        else "live deployment guardrail failure"
    )
    try:
        rolled_back = update_deployment_state_file(
            path,
            signing_key,
            to_stage="rolled_back",
            actor="runtime:auto-rollback",
            expected_generation=int(state["generation"]),
            reason=reason,
        )
        return rolled_back, report
    except (OSError, RuntimeError, ValueError):
        return state, report


def resolve_runtime_deployment(
    root: Path,
    query: str,
    decision: RouteDecision,
    intent: str,
    config: dict[str, Any],
    *,
    changed_files_count: int = 0,
    workspace_roots_count: int = 1,
) -> dict[str, Any] | None:
    if not deployment_enabled(config):
        return None

    try:
        path = _state_path(root, config)
    except ValueError:
        return _baseline_assignment("deployment_state_path_invalid")
    signing_key = _signing_key(config)
    if not signing_key:
        return _baseline_assignment("deployment_signing_key_missing")
    try:
        state = load_deployment_state(path)
    except (OSError, ValueError):
        return _baseline_assignment("deployment_state_unavailable")

    verification = verify_deployment_state(state, signing_key)
    if not verification["valid"]:
        return _baseline_assignment(
            "deployment_state_verification_failed",
            state=state,
        )

    state, guardrail_report = _auto_rollback_if_needed(
        root,
        path,
        state,
        signing_key,
        config,
    )
    if (
        isinstance(guardrail_report, dict)
        and isinstance(guardrail_report.get("gate"), dict)
        and bool(guardrail_report["gate"].get("rollback_required"))
    ):
        return _baseline_assignment(
            "deployment_auto_rollback",
            state=state,
        )

    if state.get("stage") not in LIVE_STAGES:
        return _baseline_assignment(
            f"deployment_stage_{state.get('stage')}",
            state=state,
        )
    if decision.risk.value != "low":
        return _baseline_assignment(
            "deployment_risk_locked",
            state=state,
        )

    features = build_context_features(
        query,
        decision,
        intent,
        changed_files_count=changed_files_count,
        workspace_roots_count=workspace_roots_count,
    ).to_dict()
    target_arm, key = _target_arm(state, features)
    if target_arm == BASELINE_ARM:
        return _baseline_assignment(
            "deployment_baseline_context",
            state=state,
            context=key,
            target_arm=target_arm,
        )

    probability = float(state.get("traffic_fraction", 0.0))
    if (
        not math.isfinite(probability)
        or not 0.0 < probability < 1.0
    ):
        return _baseline_assignment(
            "deployment_traffic_fraction_invalid",
            state=state,
            context=key,
            target_arm=target_arm,
        )

    fingerprint = hashlib.sha256(query.encode()).hexdigest()
    bucket = _assignment_fraction(
        signing_key,
        str(state.get("policy_id", "")),
        fingerprint,
    )
    candidate = bucket < probability
    chosen = target_arm if candidate else BASELINE_ARM
    chosen_probability = probability if candidate else 1.0 - probability
    propensities = {
        BASELINE_ARM: round(1.0 - probability, 12),
        target_arm: round(probability, 12),
    }
    deployment = {
        "assignment": "candidate" if candidate else "control",
        "reason": "signed_canary_assignment",
        "policy_id": state.get("policy_id"),
        "state_generation": int(state["generation"]),
        "stage": state.get("stage"),
        "traffic_fraction": probability,
        "candidate_probability": probability,
        "chosen_probability": chosen_probability,
        "target_arm": target_arm,
        "context_key": key,
        "assignment_bucket": round(bucket, 12),
        "source": "stage7_deployment",
    }
    return {
        "chosen_arm": chosen,
        "arm_propensities": propensities,
        "mode": "canary",
        "safety_reason": (
            "deployment_candidate"
            if candidate
            else "deployment_control"
        ),
        "deployment": deployment,
    }
