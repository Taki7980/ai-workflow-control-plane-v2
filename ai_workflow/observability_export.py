from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json


OBSERVABILITY_SCHEMA_VERSION = "ai-workflow-observability-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metric(
    name: str,
    instrument: str,
    unit: str,
    value: float | int | bool | None,
    attributes: dict[str, str],
) -> dict[str, Any]:
    return {
        "name": name,
        "instrument": instrument,
        "unit": unit,
        "value": value,
        "attributes": attributes,
    }


def build_deployment_metrics(
    report: dict[str, Any],
) -> dict[str, Any]:
    exposure = report.get("exposure")
    drift = report.get("drift")
    gate = report.get("gate")
    clustered = report.get("clustered_reward_difference")
    if not isinstance(exposure, dict):
        exposure = {}
    if not isinstance(drift, dict):
        drift = {}
    if not isinstance(gate, dict):
        gate = {}
    if not isinstance(clustered, dict):
        clustered = {}

    attributes = {
        "policy_id": str(report.get("policy_id", "")),
        "stage": str(report.get("stage", "")),
    }
    metrics = [
        _metric(
            "ai_workflow.deployment.candidate.exposure",
            "Counter",
            "{request}",
            exposure.get("candidate"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.control.exposure",
            "Counter",
            "{request}",
            exposure.get("control"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.candidate.failure_ratio",
            "Gauge",
            "1",
            exposure.get("candidate_failure_rate"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.candidate.realized_cost",
            "Counter",
            "1",
            exposure.get("cumulative_candidate_realized_cost"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.context.tv_distance",
            "Gauge",
            "1",
            drift.get("total_variation_distance"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.context.unknown_ratio",
            "Gauge",
            "1",
            drift.get("unknown_context_rate"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.guardrail.rollback_required",
            "Gauge",
            "1",
            bool(gate.get("rollback_required")),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.guardrail.safe_to_advance",
            "Gauge",
            "1",
            bool(gate.get("safe_to_advance")),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.cluster.count",
            "Gauge",
            "{cluster}",
            clustered.get("clusters"),
            attributes,
        ),
        _metric(
            "ai_workflow.deployment.cluster.reward_difference",
            "Gauge",
            "1",
            clustered.get("mean"),
            attributes,
        ),
    ]
    return {
        "schema_version": OBSERVABILITY_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "resource": {
            "service.name": "ai-workflow-control-plane",
        },
        "metrics": metrics,
        "cardinality_policy": {
            "task_fingerprint_exported": False,
            "decision_id_exported": False,
            "repository_path_exported": False,
        },
    }


def write_deployment_metrics(
    path: Path,
    report: dict[str, Any],
) -> str:
    payload = build_deployment_metrics(report)
    atomic_write_json(path, payload, sort_keys=True)
    return path.resolve().as_posix()
