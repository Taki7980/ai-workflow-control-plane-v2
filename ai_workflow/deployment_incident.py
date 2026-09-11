from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .retrieval_learning import load_learning_records


INCIDENT_SCHEMA_VERSION = "ai-workflow-deployment-incident-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _key_id(signing_key: bytes) -> str:
    return hashlib.sha256(signing_key).hexdigest()[:16]


def _sign(
    payload: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    if not signing_key:
        raise ValueError("incident signing key must not be empty")
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    digest = hmac.new(
        signing_key,
        _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    return {
        **unsigned,
        "signature": {
            "algorithm": "hmac-sha256",
            "key_id": _key_id(signing_key),
            "value": digest,
        },
    }


def verify_incident_bundle(
    payload: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != INCIDENT_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    signature = payload.get("signature")
    if not isinstance(signature, dict):
        errors.append("signature_missing")
    elif not signing_key:
        errors.append("signing_key_missing")
    else:
        unsigned = dict(payload)
        unsigned.pop("signature", None)
        expected = hmac.new(
            signing_key,
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if signature.get("algorithm") != "hmac-sha256":
            errors.append("signature_algorithm_mismatch")
        if signature.get("key_id") != _key_id(signing_key):
            errors.append("key_id_mismatch")
        supplied = str(signature.get("value", ""))
        if not hmac.compare_digest(expected, supplied):
            errors.append("signature_mismatch")
    return {
        "valid": not errors,
        "errors": errors,
        "incident_id": payload.get("incident_id"),
        "policy_id": payload.get("policy_id"),
    }


def _evidence_summary(
    root: Path,
    policy_id: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    rows = []
    for row in load_learning_records(root):
        deployment = row.get("deployment")
        if (
            isinstance(deployment, dict)
            and deployment.get("policy_id") == policy_id
        ):
            rows.append(row)
    rows = rows[-max(1, int(limit)) :]
    assignments: dict[str, int] = {}
    verified = 0
    failures = 0
    sources: dict[str, int] = {}
    decision_ids: list[str] = []
    for row in rows:
        deployment = row.get("deployment")
        if isinstance(deployment, dict):
            assignment = str(deployment.get("assignment", "unknown"))
            assignments[assignment] = assignments.get(assignment, 0) + 1
        decision_id = str(row.get("decision_id", "")).strip()
        if decision_id:
            decision_ids.append(decision_id)
        outcome = row.get("outcome")
        if isinstance(outcome, dict) and bool(outcome.get("verified")):
            verified += 1
            if not bool(outcome.get("success")):
                failures += 1
            source = str(outcome.get("source", "")).strip()
            if source:
                sources[source] = sources.get(source, 0) + 1
    return {
        "rows": len(rows),
        "assignments": dict(sorted(assignments.items())),
        "verified_outcomes": verified,
        "verified_failures": failures,
        "outcome_sources": dict(sorted(sources.items())),
        "recent_decision_ids": decision_ids[-50:],
        "raw_task_text_included": False,
        "repository_content_included": False,
    }


def create_incident_bundle(
    root: Path,
    state: dict[str, Any],
    guardrail_report: dict[str, Any],
    signing_key: bytes,
    *,
    reason: str,
) -> dict[str, Any]:
    policy_id = str(state.get("policy_id", "")).strip()
    if not policy_id:
        raise ValueError("deployment state is missing policy_id")
    created_at = _utc_now()
    gate = guardrail_report.get("gate")
    gate_summary = dict(gate) if isinstance(gate, dict) else {}
    unsigned: dict[str, Any] = {
        "schema_version": INCIDENT_SCHEMA_VERSION,
        "incident_id": "",
        "created_at": created_at,
        "policy_id": policy_id,
        "state_generation": state.get("generation"),
        "stage": state.get("stage"),
        "reason": str(reason).strip() or "deployment rollback",
        "deployment_state_sha256": _sha256(state),
        "guardrail_report_sha256": _sha256(guardrail_report),
        "state_history_tail": (
            state.get("history", [])[-1]
            if isinstance(state.get("history"), list)
            and state.get("history")
            else None
        ),
        "guardrail_gate": gate_summary,
        "evidence_summary": _evidence_summary(root, policy_id),
        "privacy": {
            "raw_task_text": False,
            "repository_content": False,
            "environment_variables": False,
            "signing_key": False,
        },
    }
    identity = hashlib.sha256(
        _canonical(
            {
                "created_at": created_at,
                "policy_id": policy_id,
                "generation": state.get("generation"),
                "reason": unsigned["reason"],
                "state_sha256": unsigned["deployment_state_sha256"],
                "guardrail_sha256": unsigned["guardrail_report_sha256"],
            }
        )
    ).hexdigest()[:24]
    unsigned["incident_id"] = identity
    return _sign(unsigned, signing_key)


def write_incident_bundle(
    root: Path,
    payload: dict[str, Any],
    signing_key: bytes,
) -> str:
    verification = verify_incident_bundle(payload, signing_key)
    if not verification["valid"]:
        raise ValueError("refusing to write invalid incident bundle")
    directory = (
        root.resolve()
        / "ai-workspace"
        / "generated"
        / "learning"
        / "deployment"
        / "incidents"
    )
    directory.mkdir(parents=True, exist_ok=True)
    incident_id = str(payload.get("incident_id", "")).strip()
    if not incident_id:
        raise ValueError("incident bundle is missing incident_id")
    path = directory / f"{incident_id}.json"
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return path.as_posix()
