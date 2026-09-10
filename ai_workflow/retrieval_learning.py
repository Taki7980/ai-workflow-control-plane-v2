from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contextual_features import (
    FEATURE_SCHEMA_VERSION,
    build_context_features,
)
from .models import RouteDecision


BASELINE_ARM = "adaptive_math"
LEARNING_MODES = frozenset({"off", "observe", "explore"})
SAFE_EXPLORATION_ARMS = (
    BASELINE_ARM,
    "source_rank",
    "bm25_rank",
    "rrf_only",
    "rrf_mmr_050",
    "rrf_mmr_075",
    "rrf_mmr_090",
)
KILL_SWITCH_ENV = "AI_WORKFLOW_LEARNING_KILL_SWITCH"


@dataclass(frozen=True)
class LearningDecision:
    decision_id: str
    policy_version: str
    mode: str
    baseline_arm: str
    eligible_arms: tuple[str, ...]
    chosen_arm: str
    chosen_propensity: float
    arm_propensities: dict[str, float]
    exploration_probability: float
    explored: bool
    safety_reason: str
    lane: str
    risk: str
    intent: str
    task_fingerprint: str
    feature_schema_version: str
    context_features: dict[str, str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _learning_config(config: dict[str, Any]) -> dict[str, Any]:
    context = config.get("context")
    if not isinstance(context, dict):
        return {}
    raw = context.get("learning")
    return dict(raw) if isinstance(raw, dict) else {}


def learning_mode(config: dict[str, Any]) -> str:
    raw = str(_learning_config(config).get("mode", "off")).strip().lower()
    return raw if raw in LEARNING_MODES else "off"


def learning_kill_switch(config: dict[str, Any]) -> bool:
    env = os.getenv(KILL_SWITCH_ENV, "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    return bool(_learning_config(config).get("kill_switch", False))


def _fraction(value: Any, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = float(value)
    if not math.isfinite(value):
        return default
    return min(1.0, max(0.0, value))


def _allowed_risks(config: dict[str, Any]) -> set[str]:
    raw = _learning_config(config).get("allowed_risks", ["low"])
    if not isinstance(raw, list):
        return {"low"}
    return {
        str(item).strip().lower()
        for item in raw
        if str(item).strip().lower() == "low"
    }


def _eligible_arms(config: dict[str, Any]) -> tuple[str, ...]:
    raw = _learning_config(config).get("eligible_arms", list(SAFE_EXPLORATION_ARMS))
    values = raw if isinstance(raw, list) else list(SAFE_EXPLORATION_ARMS)
    arms = [
        str(value).strip()
        for value in values
        if str(value).strip() in SAFE_EXPLORATION_ARMS
    ]
    if BASELINE_ARM not in arms:
        arms.insert(0, BASELINE_ARM)
    return tuple(dict.fromkeys(arms))


def _propensities(
    arms: tuple[str, ...],
    epsilon: float,
) -> dict[str, float]:
    if len(arms) <= 1 or epsilon <= 0:
        return {arm: 1.0 if arm == BASELINE_ARM else 0.0 for arm in arms}
    exploration_share = epsilon / len(arms)
    return {
        arm: (
            1.0 - epsilon + exploration_share
            if arm == BASELINE_ARM
            else exploration_share
        )
        for arm in arms
    }


def _sample_arm(
    propensities: dict[str, float],
    rng: random.Random,
) -> str:
    point = rng.random()
    cumulative = 0.0
    last = BASELINE_ARM
    for arm, probability in propensities.items():
        last = arm
        cumulative += probability
        if point <= cumulative:
            return arm
    return last


def choose_learning_decision(
    query: str,
    decision: RouteDecision,
    intent: str,
    config: dict[str, Any],
    *,
    changed_files_count: int = 0,
    workspace_roots_count: int = 1,
    rng: random.Random | None = None,
) -> LearningDecision:
    mode = learning_mode(config)
    cfg = _learning_config(config)
    epsilon = _fraction(cfg.get("exploration_probability", 0.05), 0.05)
    arms = _eligible_arms(config)
    risk = decision.risk.value
    safety_reason = "learning_disabled"
    chosen = BASELINE_ARM
    propensities = {BASELINE_ARM: 1.0}
    explored = False

    if mode == "observe":
        safety_reason = "observe_only"
    elif mode == "explore":
        if learning_kill_switch(config):
            safety_reason = "kill_switch"
        elif risk not in _allowed_risks(config):
            safety_reason = "risk_locked"
        elif len(arms) <= 1 or epsilon <= 0:
            safety_reason = "no_exploration_mass"
        else:
            propensities = _propensities(arms, epsilon)
            source = rng if rng is not None else random.SystemRandom()
            chosen = _sample_arm(propensities, source)
            explored = chosen != BASELINE_ARM
            safety_reason = "bounded_exploration" if explored else "baseline_sample"

    fingerprint = hashlib.sha256(query.encode()).hexdigest()
    features = build_context_features(
        query,
        decision,
        intent,
        changed_files_count=changed_files_count,
        workspace_roots_count=workspace_roots_count,
    )
    return LearningDecision(
        decision_id=uuid.uuid4().hex,
        policy_version="safe-epsilon-v1",
        mode=mode,
        baseline_arm=BASELINE_ARM,
        eligible_arms=tuple(propensities),
        chosen_arm=chosen,
        chosen_propensity=float(propensities.get(chosen, 1.0)),
        arm_propensities={
            arm: round(float(probability), 12)
            for arm, probability in propensities.items()
        },
        exploration_probability=epsilon if mode == "explore" else 0.0,
        explored=explored,
        safety_reason=safety_reason,
        lane=decision.lane.value,
        risk=risk,
        intent=str(intent),
        task_fingerprint=fingerprint,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        context_features=features.to_dict(),
        created_at=_utc_now(),
    )


def baseline_fallback(
    source: LearningDecision,
    reason: str,
) -> LearningDecision:
    return LearningDecision(
        decision_id=uuid.uuid4().hex,
        policy_version=source.policy_version,
        mode=source.mode,
        baseline_arm=BASELINE_ARM,
        eligible_arms=(BASELINE_ARM,),
        chosen_arm=BASELINE_ARM,
        chosen_propensity=1.0,
        arm_propensities={BASELINE_ARM: 1.0},
        exploration_probability=0.0,
        explored=False,
        safety_reason=reason,
        lane=source.lane,
        risk=source.risk,
        intent=source.intent,
        task_fingerprint=source.task_fingerprint,
        feature_schema_version=source.feature_schema_version,
        context_features=dict(source.context_features),
        created_at=_utc_now(),
    )


def learning_root(root: Path) -> Path:
    return root.resolve() / "ai-workspace" / "generated" / "learning"


def _record_path(root: Path, kind: str, decision_id: str) -> Path:
    if (
        len(decision_id) != 32
        or any(ch not in "0123456789abcdef" for ch in decision_id)
    ):
        raise ValueError("decision_id must be a 32-character lowercase hexadecimal ID")
    return learning_root(root) / kind / f"{decision_id}.json"


def _write_immutable(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return path.as_posix()


def write_learning_decision(
    root: Path,
    decision: LearningDecision,
) -> str:
    return _write_immutable(
        _record_path(root, "decisions", decision.decision_id),
        decision.to_dict(),
    )


def prepare_learning_decision(
    root: Path,
    query: str,
    decision: RouteDecision,
    intent: str,
    config: dict[str, Any],
    *,
    changed_files_count: int = 0,
    workspace_roots_count: int = 1,
    rng: random.Random | None = None,
) -> tuple[LearningDecision, str | None]:
    selected = choose_learning_decision(
        query,
        decision,
        intent,
        config,
        changed_files_count=changed_files_count,
        workspace_roots_count=workspace_roots_count,
        rng=rng,
    )
    if selected.mode == "off":
        return selected, None
    try:
        return selected, write_learning_decision(root, selected)
    except OSError:
        if selected.chosen_arm == BASELINE_ARM:
            return selected, None
        fallback = baseline_fallback(selected, "decision_log_failure")
        try:
            return fallback, write_learning_decision(root, fallback)
        except OSError:
            return fallback, None


def write_learning_observation(
    root: Path,
    decision_id: str,
    *,
    elapsed_ms: float,
    used_chars: int,
    fallback_count: int,
    sufficiency_score: float,
    evidence_state: str,
) -> str:
    payload = {
        "decision_id": decision_id,
        "observed_at": _utc_now(),
        "elapsed_ms": round(max(0.0, float(elapsed_ms)), 4),
        "used_chars": max(0, int(used_chars)),
        "fallback_count": max(0, int(fallback_count)),
        "sufficiency_score": round(
            min(1.0, max(0.0, float(sufficiency_score))),
            6,
        ),
        "evidence_state": str(evidence_state),
    }
    return _write_immutable(
        _record_path(root, "observations", decision_id),
        payload,
    )


def record_verified_outcome(
    root: Path,
    decision_id: str,
    *,
    success: bool,
    source: str,
    reward: float | None = None,
    realized_cost: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> str:
    decision_path = _record_path(root, "decisions", decision_id)
    if not decision_path.exists():
        raise ValueError(f"unknown learning decision: {decision_id}")
    try:
        decision_record = json.loads(
            decision_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"learning decision is unreadable: {decision_id}"
        ) from exc
    if not isinstance(decision_record, dict):
        raise ValueError(f"learning decision is invalid: {decision_id}")
    if not str(source).strip():
        raise ValueError("outcome source must not be blank")
    value = float(success) if reward is None else float(reward)
    cost = float(realized_cost)
    if not math.isfinite(value) or not math.isfinite(cost) or cost < 0:
        raise ValueError(
            "reward must be finite and realized_cost must be "
            "finite/non-negative"
        )

    recorded_at = _utc_now()
    created_at = str(decision_record.get("created_at", "")).strip()
    delay_seconds: float | None = None
    if created_at:
        try:
            created = datetime.fromisoformat(created_at)
            recorded = datetime.fromisoformat(recorded_at)
            if created.tzinfo is not None and recorded.tzinfo is not None:
                delay_seconds = max(
                    0.0,
                    (recorded - created).total_seconds(),
                )
        except ValueError:
            delay_seconds = None

    payload = {
        "decision_id": decision_id,
        "verified": True,
        "success": bool(success),
        "reward": value,
        "realized_cost": cost,
        "source": str(source).strip(),
        "recorded_at": recorded_at,
        "decision_created_at": created_at or None,
        "verification_delay_seconds": (
            round(delay_seconds, 6)
            if delay_seconds is not None
            else None
        ),
        "metadata": dict(metadata or {}),
    }
    return _write_immutable(
        _record_path(root, "outcomes", decision_id),
        payload,
    )


def _read_records(directory: Path) -> dict[str, dict[str, Any]]:
    if not directory.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        decision_id = str(value.get("decision_id", "")).strip()
        if decision_id:
            records[decision_id] = value
    return records


def load_learning_records(root: Path) -> list[dict[str, Any]]:
    base = learning_root(root)
    decisions = _read_records(base / "decisions")
    observations = _read_records(base / "observations")
    outcomes = _read_records(base / "outcomes")
    rows: list[dict[str, Any]] = []
    for decision_id, decision in sorted(decisions.items()):
        row = dict(decision)
        row["observation"] = observations.get(decision_id)
        row["outcome"] = outcomes.get(decision_id)
        rows.append(row)
    return rows


def learning_status(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    rows = load_learning_records(root)
    return {
        "mode": learning_mode(config),
        "kill_switch": learning_kill_switch(config),
        "kill_switch_env": KILL_SWITCH_ENV,
        "baseline_arm": BASELINE_ARM,
        "safe_exploration_arms": list(SAFE_EXPLORATION_ARMS),
        "decisions": len(rows),
        "observations": sum(isinstance(row.get("observation"), dict) for row in rows),
        "verified_outcomes": sum(isinstance(row.get("outcome"), dict) for row in rows),
    }


def apply_learning_arm(
    config: dict[str, Any],
    arm: str,
) -> dict[str, Any]:
    if arm not in SAFE_EXPLORATION_ARMS:
        raise ValueError(f"unsafe or unknown retrieval arm: {arm}")
    out = copy.deepcopy(config)
    if arm == BASELINE_ARM:
        return out
    experiments = out.setdefault("context", {}).setdefault("experiments", {})
    if arm == "source_rank":
        experiments["hybrid_ranker"] = "source"
    elif arm == "bm25_rank":
        experiments["hybrid_ranker"] = "bm25"
    elif arm == "rrf_only":
        experiments["hybrid_ranker"] = "rrf"
    elif arm.startswith("rrf_mmr_"):
        experiments["hybrid_ranker"] = "rrf_mmr"
        experiments["mmr_lambda"] = int(arm.rsplit("_", 1)[1]) / 100.0
    return out
