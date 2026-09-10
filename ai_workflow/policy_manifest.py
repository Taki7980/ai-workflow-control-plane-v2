from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from .contextual_features import (
    FEATURE_SCHEMA_VERSION,
    validate_context_fields,
)
from .retrieval_learning import BASELINE_ARM, SAFE_EXPLORATION_ARMS


MANIFEST_SCHEMA_VERSION = "retrieval-policy-manifest-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report_digest(report: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(report)).hexdigest()


def _identity_payload(
    *,
    feature_schema_version: str,
    context_fields: list[str],
    policy: dict[str, str],
    evidence_cutoff: str,
    source_report_sha256: str,
) -> dict[str, Any]:
    return {
        "feature_schema_version": feature_schema_version,
        "context_fields": context_fields,
        "policy": policy,
        "evidence_cutoff": evidence_cutoff,
        "source_report_sha256": source_report_sha256,
        "fallback_arm": BASELINE_ARM,
    }


def _policy_id(identity: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(identity)).hexdigest()[:32]


def _key_id(signing_key: bytes) -> str:
    return hashlib.sha256(signing_key).hexdigest()[:16]


def _validate_policy(policy: Any) -> dict[str, str]:
    if not isinstance(policy, dict) or not policy:
        raise ValueError("contextual policy must be a non-empty object")
    out: dict[str, str] = {}
    for key, value in policy.items():
        context = str(key).strip()
        arm = str(value).strip()
        if not context:
            raise ValueError("contextual policy contains a blank context key")
        if arm not in SAFE_EXPLORATION_ARMS:
            raise ValueError(f"contextual policy contains unsafe arm: {arm}")
        out[context] = arm
    return dict(sorted(out.items()))


def create_policy_manifest(
    report: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    if not signing_key:
        raise ValueError("signing key must not be empty")
    if report.get("scope") != "contextual-retrieval-policy-development":
        raise ValueError("input is not a Stage 6 contextual policy report")
    promotion = report.get("promotion")
    if (
        not isinstance(promotion, dict)
        or not bool(promotion.get("eligible_for_shadow"))
    ):
        raise ValueError(
            "contextual policy is not eligible for shadow evaluation"
        )
    if report.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ValueError("contextual policy feature schema is incompatible")

    fields_raw = report.get("context_fields")
    if not isinstance(fields_raw, list):
        raise ValueError("contextual policy is missing context fields")
    fields = list(validate_context_fields(fields_raw))
    policy = _validate_policy(report.get("development_policy"))
    cutoff = str(report.get("evidence_cutoff", "")).strip()
    if not cutoff:
        raise ValueError("contextual policy is missing an evidence cutoff")

    report_sha = _report_digest(report)
    identity = _identity_payload(
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        context_fields=fields,
        policy=policy,
        evidence_cutoff=cutoff,
        source_report_sha256=report_sha,
    )
    policy_id = _policy_id(identity)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "policy_id": policy_id,
        "created_at": _utc_now(),
        "status": "shadow_only",
        "automatic_runtime_activation": False,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "context_fields": fields,
        "policy": policy,
        "fallback_arm": BASELINE_ARM,
        "locked_risks": ["medium", "high"],
        "evidence_cutoff": cutoff,
        "source_report_sha256": report_sha,
        "source_decision_sha256": report.get(
            "source_decision_sha256"
        ),
        "reward_model": report.get("reward_model"),
        "cost_model": report.get("cost_model"),
        "holdout_evidence": report.get(
            "holdout_doubly_robust_evaluation"
        ),
        "rollback": {
            "target_arm": BASELINE_ARM,
            "reason": (
                "deterministic production baseline remains the rollback target"
            ),
        },
        "provenance": {
            "development_events": report.get("development_events"),
            "holdout_events": report.get("holdout_events"),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        },
    }
    signature = hmac.new(
        signing_key,
        _canonical(manifest),
        hashlib.sha256,
    ).hexdigest()
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": _key_id(signing_key),
        "value": signature,
    }
    return manifest


def verify_policy_manifest(
    manifest: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    errors: list[str] = []
    if not signing_key:
        errors.append("signing_key_missing")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if manifest.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        errors.append("feature_schema_mismatch")

    fields_raw = manifest.get("context_fields")
    try:
        fields = (
            list(validate_context_fields(fields_raw))
            if isinstance(fields_raw, list)
            else []
        )
    except ValueError:
        fields = []
        errors.append("invalid_context_fields")
    try:
        policy = _validate_policy(manifest.get("policy"))
    except ValueError:
        policy = {}
        errors.append("invalid_policy")

    cutoff = str(manifest.get("evidence_cutoff", "")).strip()
    source_report_sha = str(
        manifest.get("source_report_sha256", "")
    ).strip()
    if not cutoff:
        errors.append("missing_evidence_cutoff")
    if not source_report_sha:
        errors.append("missing_source_report_sha256")

    if fields and policy and cutoff and source_report_sha:
        identity = _identity_payload(
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            context_fields=fields,
            policy=policy,
            evidence_cutoff=cutoff,
            source_report_sha256=source_report_sha,
        )
        if manifest.get("policy_id") != _policy_id(identity):
            errors.append("policy_id_mismatch")

    signature = manifest.get("signature")
    if not isinstance(signature, dict):
        errors.append("signature_missing")
    elif signature.get("algorithm") != "hmac-sha256":
        errors.append("signature_algorithm_mismatch")
    elif signing_key:
        unsigned = dict(manifest)
        unsigned.pop("signature", None)
        expected = hmac.new(
            signing_key,
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        supplied = str(signature.get("value", ""))
        if not hmac.compare_digest(expected, supplied):
            errors.append("signature_mismatch")
        if signature.get("key_id") != _key_id(signing_key):
            errors.append("key_id_mismatch")

    if manifest.get("status") != "shadow_only":
        errors.append("status_mismatch")
    if manifest.get("fallback_arm") != BASELINE_ARM:
        errors.append("fallback_arm_mismatch")
    rollback = manifest.get("rollback")
    if (
        not isinstance(rollback, dict)
        or rollback.get("target_arm") != BASELINE_ARM
    ):
        errors.append("rollback_target_mismatch")
    locked = manifest.get("locked_risks")
    if locked != ["medium", "high"]:
        errors.append("locked_risks_mismatch")
    if bool(manifest.get("automatic_runtime_activation")):
        errors.append("automatic_activation_forbidden")

    return {
        "valid": not errors,
        "errors": errors,
        "policy_id": manifest.get("policy_id"),
        "status": manifest.get("status"),
        "automatic_runtime_activation": False,
        "rollback_target": BASELINE_ARM,
    }
