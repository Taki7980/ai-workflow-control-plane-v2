from __future__ import annotations

from pathlib import Path
from ..config import load_config
from ..deployment_guardrails import evaluate_live_guardrails
from ..deployment_incident import (
    create_incident_bundle,
    verify_incident_bundle,
    write_incident_bundle,
)
from ..deployment_state import (
    create_deployment_state,
    load_deployment_state,
    update_deployment_state_file,
    verify_deployment_state,
    write_new_deployment_state,
)
from ..io_utils import atomic_write_json
from ..observability_export import (
    build_deployment_metrics,
    write_deployment_metrics,
)
from ..production_store import mirror_learning_event

from .common import _json, _load_json_object, _root, _signing_key_from_env

def _deployment_state_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("deployment state path must stay inside project root")
    return resolved

def cmd_deployment_create(args):
    root = _root(args)
    signing_key = _signing_key_from_env(args.signing_key_env)
    state = create_deployment_state(
        root,
        _load_json_object(args.manifest),
        _load_json_object(args.shadow_report),
        signing_key,
        approved_by=args.approved_by,
        bounded_traffic_fraction=args.bounded_traffic,
        reward_min=args.reward_min,
        reward_max=args.reward_max,
        max_importance_weight=args.max_importance_weight,
        minimum_monitor_outcomes=args.minimum_monitor_outcomes,
        promotion_margin=args.promotion_margin,
        max_reward_regression=args.max_reward_regression,
        max_failure_rate=args.max_failure_rate,
        max_context_tv_distance=args.max_context_tv_distance,
        max_unknown_context_rate=args.max_unknown_context_rate,
        minimum_drift_samples=args.minimum_drift_samples,
        drift_window=args.drift_window,
        minimum_monitor_clusters=args.minimum_monitor_clusters,
        cluster_bootstrap_resamples=args.cluster_bootstrap_resamples,
        cluster_bootstrap_seed=args.cluster_bootstrap_seed,
        max_cumulative_realized_cost=args.max_cumulative_realized_cost,
    )
    path = _deployment_state_path(root, args.state)
    write_new_deployment_state(path, state, signing_key)
    mirror_learning_event(
        root,
        load_config(root),
        "deployment_state",
        state,
    )
    _json({
        "created": True,
        "policy_id": state["policy_id"],
        "stage": state["stage"],
        "generation": state["generation"],
        "traffic_fraction": state["traffic_fraction"],
        "state": path.relative_to(root).as_posix(),
    })

def cmd_deployment_status(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    verification = verify_deployment_state(
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    _json({
        **verification,
        "state": path.relative_to(root).as_posix(),
        "history_tail": (
            state.get("history", [])[-1]
            if isinstance(state.get("history"), list)
            and state.get("history")
            else None
        ),
        "guardrails": state.get("guardrails"),
    })
    if not verification["valid"]:
        raise SystemExit(1)

def cmd_deployment_guardrails(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    result = evaluate_live_guardrails(
        root,
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)

def cmd_deployment_promote(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    guardrail_report = (
        _load_json_object(args.guardrail_report)
        if args.guardrail_report
        else None
    )
    updated = update_deployment_state_file(
        path,
        _signing_key_from_env(args.signing_key_env),
        to_stage=args.to,
        actor=args.actor,
        expected_generation=args.expected_generation,
        guardrail_report=guardrail_report,
        reason=args.reason,
    )
    mirror_learning_event(
        root,
        load_config(root),
        "deployment_state",
        updated,
    )
    _json({
        "updated": True,
        "policy_id": updated["policy_id"],
        "stage": updated["stage"],
        "generation": updated["generation"],
        "traffic_fraction": updated["traffic_fraction"],
        "state": path.relative_to(root).as_posix(),
    })

def cmd_deployment_rollback(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    signing_key = _signing_key_from_env(args.signing_key_env)
    current = load_deployment_state(path)
    try:
        guardrail_report = evaluate_live_guardrails(
            root,
            current,
            signing_key,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        guardrail_report = {
            "scope": "manual-rollback-diagnostic-unavailable",
            "policy_id": current.get("policy_id"),
            "stage": current.get("stage"),
            "state_generation": current.get("generation"),
            "gate": {
                "rollback_required": True,
                "safe_to_advance": False,
                "rollback_blockers": ["manual_rollback"],
                "diagnostic_error": type(exc).__name__,
            },
        }
    updated = update_deployment_state_file(
        path,
        signing_key,
        to_stage="rolled_back",
        actor=args.actor,
        expected_generation=args.expected_generation,
        reason=args.reason,
    )
    config = load_config(root)
    mirror_learning_event(
        root,
        config,
        "deployment_state",
        updated,
    )
    incident_path = None
    deployment_cfg = (
        config.get("context", {}).get("deployment", {})
        if isinstance(config.get("context"), dict)
        else {}
    )
    if (
        isinstance(deployment_cfg, dict)
        and bool(deployment_cfg.get("incident_bundles", True))
    ):
        try:
            incident = create_incident_bundle(
                root,
                updated,
                guardrail_report,
                signing_key,
                reason=args.reason,
            )
            incident_path = write_incident_bundle(
                root,
                incident,
                signing_key,
            )
            mirror_learning_event(
                root,
                config,
                "deployment_incident",
                incident,
            )
        except (OSError, RuntimeError, ValueError):
            incident_path = None
    _json({
        "updated": True,
        "policy_id": updated["policy_id"],
        "stage": updated["stage"],
        "generation": updated["generation"],
        "traffic_fraction": updated["traffic_fraction"],
        "rollback": updated.get("rollback"),
        "incident_bundle": (
            Path(incident_path).relative_to(root.resolve()).as_posix()
            if incident_path is not None
            else None
        ),
        "state": path.relative_to(root).as_posix(),
    })

def cmd_deployment_metrics(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    report = evaluate_live_guardrails(
        root,
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    payload = build_deployment_metrics(report)
    if args.output:
        write_deployment_metrics(Path(args.output), report)
    _json(payload)

def cmd_deployment_verify_incident(args):
    payload = _load_json_object(args.input)
    result = verify_incident_bundle(
        payload,
        _signing_key_from_env(args.signing_key_env),
    )
    _json(result)
    if not result["valid"]:
        raise SystemExit(1)
