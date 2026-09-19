from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .models import ContextItem, RouteDecision


class Capability(str, Enum):
    """Privileged effects a post-LLM action may request."""

    TOOL_EXECUTION = "tool_execution"
    PROVIDER_SELECTION = "provider_selection"
    REPOSITORY_ACTIVATION = "repository_activation"
    NETWORK_ACCESS = "network_access"
    SECRET_ACCESS = "secret_access"  # noqa: S105 - capability label, not a credential
    SAFETY_LANE_CHANGE = "safety_lane_change"
    SKIP_VERIFICATION = "skip_verification"


class DenialReason(str, Enum):
    """Stable machine-readable denial reasons."""

    UNKNOWN_EVIDENCE = "unknown_evidence"
    INVALID_REQUEST = "invalid_request"
    TOOL_NOT_ALLOWLISTED = "tool_not_allowlisted"
    CONTROL_PLANE_OWNED = "control_plane_owned_capability"
    OPERATOR_OWNED = "operator_owned_capability"
    TRUSTED_RUNTIME_GRANT_REQUIRED = "trusted_runtime_grant_required"
    VERIFICATION_REQUIRED = "verification_required"
    CAPABILITY_NOT_GRANTED = "capability_not_granted"


@dataclass(frozen=True)
class ModelActionRequest:
    """A model-proposed action presented to the deterministic gate."""

    capability: Capability
    tool_name: str | None = None
    provider_id: str | None = None
    repository_id: str | None = None
    network_host: str | None = None
    secret_name: str | None = None
    requested_lane: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    cited_evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelCapabilityPolicy:
    """Pre-LLM policy. Untrusted evidence cannot mutate this object."""

    schema: str
    lane: str
    risk: str
    allowed_tools: tuple[str, ...]
    active_repository_ids: tuple[str, ...]
    verification_passes: int
    denied_by_default: tuple[str, ...]
    policy_owner: str = "control_plane"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lane": self.lane,
            "risk": self.risk,
            "allowed_tools": list(self.allowed_tools),
            "active_repository_ids": list(self.active_repository_ids),
            "verification_passes": self.verification_passes,
            "denied_by_default": list(self.denied_by_default),
            "policy_owner": self.policy_owner,
        }


@dataclass(frozen=True)
class AuthorizationDecision:
    """Bound authorization result for one exact proposed action."""

    allowed: bool
    reason: str
    capability: Capability
    request_digest: str
    policy_schema: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "capability": self.capability.value,
            "request_digest": self.request_digest,
            "policy_schema": self.policy_schema,
        }


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("action parameters must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise ValueError("action parameter keys must be non-empty strings")
            normalized[raw_key] = _canonical_value(raw_value)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise ValueError(
        f"unsupported action parameter type: {type(value).__name__}"
    )


def action_request_digest(request: ModelActionRequest) -> str:
    payload = {
        "schema": "model-action-v1",
        "capability": request.capability.value,
        "tool_name": request.tool_name,
        "provider_id": request.provider_id,
        "repository_id": request.repository_id,
        "network_host": request.network_host,
        "secret_name": request.secret_name,
        "requested_lane": request.requested_lane,
        "parameters": _canonical_value(dict(request.parameters)),
        "cited_evidence_ids": sorted(set(request.cited_evidence_ids)),
    }
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _evidence_ids(items: Sequence[ContextItem]) -> set[str]:
    return {
        item.evidence.evidence_id
        for item in items
        if item.evidence is not None
    }


def build_model_capability_policy(
    decision: RouteDecision,
    orchestration: Mapping[str, Any],
    evidence: Sequence[ContextItem],
) -> ModelCapabilityPolicy:
    """Build the post-LLM policy exclusively from control-plane state.

    Repository/provider/memory text is not consulted for permissions. Evidence
    contributes only stable repository identities for diagnostics/scope.
    """

    raw_tools = orchestration.get("crg_plan") or ()
    allowed_tools = tuple(
        dict.fromkeys(
            str(tool).strip()
            for tool in raw_tools
            if isinstance(tool, str) and tool.strip()
        )
    )
    try:
        verification_passes = max(
            1,
            int(orchestration.get("verification_passes", 1)),
        )
    except (TypeError, ValueError):
        verification_passes = 1

    repositories = tuple(
        sorted(
            {
                item.evidence.repository_id
                for item in evidence
                if item.evidence is not None
                and item.evidence.repository_id
            }
        )
    )
    denied = (
        Capability.PROVIDER_SELECTION.value,
        Capability.REPOSITORY_ACTIVATION.value,
        Capability.NETWORK_ACCESS.value,
        Capability.SECRET_ACCESS.value,
        Capability.SAFETY_LANE_CHANGE.value,
        Capability.SKIP_VERIFICATION.value,
        "tool_execution_unless_allowlisted",
    )
    return ModelCapabilityPolicy(
        schema="capability-v1",
        lane=decision.lane.value,
        risk=decision.risk.value,
        allowed_tools=allowed_tools,
        active_repository_ids=repositories,
        verification_passes=verification_passes,
        denied_by_default=denied,
    )


def _decision(
    policy: ModelCapabilityPolicy,
    request: ModelActionRequest,
    *,
    allowed: bool,
    reason: str,
    digest: str,
) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=allowed,
        reason=reason,
        capability=request.capability,
        request_digest=digest,
        policy_schema=policy.schema,
    )


def authorize_model_action(
    policy: ModelCapabilityPolicy,
    request: ModelActionRequest,
    evidence: Sequence[ContextItem],
) -> AuthorizationDecision:
    """Authorize a model-proposed action without consulting model reasoning.

    The decision depends only on the immutable pre-LLM policy, the structured
    requested action, and whether cited evidence IDs actually exist. Retrieved
    text and evidence authority claims never grant capabilities.
    """

    try:
        digest = action_request_digest(request)
    except (TypeError, ValueError):
        digest = "sha256:" + ("0" * 64)
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.INVALID_REQUEST.value,
            digest=digest,
        )

    known_evidence = _evidence_ids(evidence)
    if any(
        evidence_id not in known_evidence
        for evidence_id in request.cited_evidence_ids
    ):
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.UNKNOWN_EVIDENCE.value,
            digest=digest,
        )

    if request.capability == Capability.TOOL_EXECUTION:
        tool_name = str(request.tool_name or "").strip()
        if not tool_name:
            return _decision(
                policy,
                request,
                allowed=False,
                reason=DenialReason.INVALID_REQUEST.value,
                digest=digest,
            )
        if tool_name in policy.allowed_tools:
            return _decision(
                policy,
                request,
                allowed=True,
                reason="preauthorized_tool",
                digest=digest,
            )
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.TOOL_NOT_ALLOWLISTED.value,
            digest=digest,
        )

    if request.capability == Capability.PROVIDER_SELECTION:
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.CONTROL_PLANE_OWNED.value,
            digest=digest,
        )

    if request.capability == Capability.REPOSITORY_ACTIVATION:
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.OPERATOR_OWNED.value,
            digest=digest,
        )

    if request.capability in {
        Capability.NETWORK_ACCESS,
        Capability.SECRET_ACCESS,
    }:
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.TRUSTED_RUNTIME_GRANT_REQUIRED.value,
            digest=digest,
        )

    if request.capability == Capability.SAFETY_LANE_CHANGE:
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.CONTROL_PLANE_OWNED.value,
            digest=digest,
        )

    if request.capability == Capability.SKIP_VERIFICATION:
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.VERIFICATION_REQUIRED.value,
            digest=digest,
        )

    return _decision(
        policy,
        request,
        allowed=False,
        reason=DenialReason.CAPABILITY_NOT_GRANTED.value,
        digest=digest,
    )
