from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .models import ContextItem, RouteDecision


_MAX_PARAMETER_DEPTH = 6
_MAX_PARAMETER_NODES = 256
_MAX_PARAMETER_STRING_CHARS = 4096

_PRIVILEGED_PARAMETER_KEYS = frozenset(
    {
        "command",
        "commands",
        "shell",
        "argv",
        "executable",
        "network_host",
        "host",
        "hostname",
        "url",
        "uri",
        "endpoint_url",
        "secret",
        "secret_name",
        "secrets",
        "token",
        "api_key",
        "credential",
        "credentials",
        "provider",
        "provider_id",
        "requested_lane",
        "lane",
        "risk",
        "skip_verification",
        "verification_passes",
        "repository_activation",
        "activate_repository",
    }
)
_REPOSITORY_PARAMETER_KEYS = frozenset(
    {"repository_id", "repo_id"}
)
_DEPTH_PARAMETER_KEYS = frozenset(
    {"depth", "graph_depth", "max_depth"}
)
_PATH_PARAMETER_KEYS = frozenset(
    {
        "path",
        "file",
        "files",
        "changed_file",
        "changed_files",
        "source_path",
        "target_path",
    }
)


class _ParameterBudgetError(ValueError):
    """Structured action parameters exceeded deterministic safety bounds."""


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
    PRIVILEGED_PARAMETER = "privileged_parameter"
    REPOSITORY_SCOPE_VIOLATION = "repository_scope_violation"
    REPOSITORY_SCOPE_REQUIRED = "repository_scope_required"
    PATH_SCOPE_VIOLATION = "path_scope_violation"
    GRAPH_DEPTH_EXCEEDED = "graph_depth_exceeded"
    PARAMETER_BUDGET_EXCEEDED = "parameter_budget_exceeded"


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
    max_graph_depth: int
    denied_by_default: tuple[str, ...]
    task_digest: str | None = None
    policy_owner: str = "control_plane"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lane": self.lane,
            "risk": self.risk,
            "allowed_tools": list(self.allowed_tools),
            "active_repository_ids": list(self.active_repository_ids),
            "verification_passes": self.verification_passes,
            "max_graph_depth": self.max_graph_depth,
            "denied_by_default": list(self.denied_by_default),
            "task_digest": self.task_digest,
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
    task_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "capability": self.capability.value,
            "request_digest": self.request_digest,
            "policy_schema": self.policy_schema,
            "task_digest": self.task_digest,
        }


def task_scope_digest(task_text: str | None) -> str | None:
    """Bind policy evidence to the original task without persisting task text."""

    if task_text is None:
        return None
    normalized = " ".join(str(task_text).split())
    raw = ("task-scope-v1\0" + normalized).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_value(
    value: Any,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
) -> Any:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > _MAX_PARAMETER_NODES or depth > _MAX_PARAMETER_DEPTH:
        raise _ParameterBudgetError(
            "action parameters exceed structural budget"
        )

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_PARAMETER_STRING_CHARS:
            raise _ParameterBudgetError(
                "action parameter string is too large"
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("action parameters must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        if len(value) > _MAX_PARAMETER_NODES:
            raise _ParameterBudgetError(
                "action parameter mapping is too large"
            )
        for raw_key, raw_value in value.items():
            if (
                not isinstance(raw_key, str)
                or not raw_key
                or len(raw_key) > 128
            ):
                raise ValueError(
                    "action parameter keys must be bounded non-empty strings"
                )
            normalized[raw_key] = _canonical_value(
                raw_value,
                depth=depth + 1,
                budget=budget,
            )
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_PARAMETER_NODES:
            raise _ParameterBudgetError(
                "action parameter sequence is too large"
            )
        return [
            _canonical_value(
                item,
                depth=depth + 1,
                budget=budget,
            )
            for item in value
        ]
    raise ValueError(
        f"unsupported action parameter type: {type(value).__name__}"
    )


def action_request_digest(request: ModelActionRequest) -> str:
    payload = {
        "schema": "model-action-v2",
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


def _normalized_parameter_key(value: str) -> str:
    return value.strip().casefold().replace("-", "_")


def _is_path_key(key: str) -> bool:
    return (
        key in _PATH_PARAMETER_KEYS
        or key.endswith("_path")
        or key.endswith("_file")
        or key.endswith("_files")
    )


def _safe_relative_path(value: str) -> bool:
    raw = str(value).strip().replace("\\", "/")
    if (
        not raw
        or "\x00" in raw
        or raw.startswith(("/", "~"))
        or "://" in raw
        or re.match(r"^[A-Za-z]:", raw)
    ):
        return False
    parts = PurePosixPath(raw).parts
    return all(part not in {"..", ""} for part in parts)


def _path_values_are_safe(value: Any) -> bool:
    if isinstance(value, str):
        return _safe_relative_path(value)
    if isinstance(value, (list, tuple)):
        return bool(value) and all(
            isinstance(item, str) and _safe_relative_path(item)
            for item in value
        )
    return False


def _validate_tool_parameters(
    policy: ModelCapabilityPolicy,
    parameters: Mapping[str, Any],
) -> tuple[str | None, set[str]]:
    repositories: set[str] = set()
    node_budget = [0]

    def walk(value: Any, *, key: str | None, depth: int) -> str | None:
        node_budget[0] += 1
        if (
            node_budget[0] > _MAX_PARAMETER_NODES
            or depth > _MAX_PARAMETER_DEPTH
        ):
            return DenialReason.PARAMETER_BUDGET_EXCEEDED.value

        if key is not None:
            normalized_key = _normalized_parameter_key(key)
            if normalized_key in _PRIVILEGED_PARAMETER_KEYS:
                return DenialReason.PRIVILEGED_PARAMETER.value

            if normalized_key in _REPOSITORY_PARAMETER_KEYS:
                if not isinstance(value, str) or not value.strip():
                    return DenialReason.INVALID_REQUEST.value
                repository_id = value.strip()
                if repository_id not in policy.active_repository_ids:
                    return DenialReason.REPOSITORY_SCOPE_VIOLATION.value
                repositories.add(repository_id)

            if normalized_key in _DEPTH_PARAMETER_KEYS:
                if isinstance(value, bool) or not isinstance(value, int):
                    return DenialReason.INVALID_REQUEST.value
                if value < 0 or value > policy.max_graph_depth:
                    return DenialReason.GRAPH_DEPTH_EXCEEDED.value

            if _is_path_key(normalized_key):
                if not _path_values_are_safe(value):
                    return DenialReason.PATH_SCOPE_VIOLATION.value

        if isinstance(value, Mapping):
            for raw_key, raw_value in value.items():
                if not isinstance(raw_key, str) or not raw_key:
                    return DenialReason.INVALID_REQUEST.value
                reason = walk(
                    raw_value,
                    key=raw_key,
                    depth=depth + 1,
                )
                if reason is not None:
                    return reason
        elif isinstance(value, (list, tuple)):
            for item in value:
                reason = walk(item, key=None, depth=depth + 1)
                if reason is not None:
                    return reason
        elif isinstance(value, str):
            if len(value) > _MAX_PARAMETER_STRING_CHARS:
                return DenialReason.PARAMETER_BUDGET_EXCEEDED.value
        elif value is None or isinstance(value, (bool, int)):
            pass
        elif isinstance(value, float):
            if not math.isfinite(value):
                return DenialReason.INVALID_REQUEST.value
        else:
            return DenialReason.INVALID_REQUEST.value
        return None

    reason = walk(parameters, key=None, depth=0)
    return reason, repositories


def build_model_capability_policy(
    decision: RouteDecision,
    orchestration: Mapping[str, Any],
    evidence: Sequence[ContextItem],
    *,
    task_text: str | None = None,
) -> ModelCapabilityPolicy:
    """Build the post-LLM policy exclusively from control-plane state.

    Repository/provider/memory text is not consulted for permissions. Evidence
    contributes only system-assigned repository identities for scope.
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

    raw_budget = orchestration.get("budget") or {}
    try:
        requested_depth = int(orchestration.get("graph_depth", 1))
    except (TypeError, ValueError):
        requested_depth = 1
    try:
        budget_depth = int(
            raw_budget.get("max_graph_depth", requested_depth)
        )
    except (AttributeError, TypeError, ValueError):
        budget_depth = requested_depth
    max_graph_depth = max(1, min(requested_depth, budget_depth))

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
        "tool_execution_unless_allowlisted_and_scoped",
        "privileged_parameters_from_model",
        "repository_scope_expansion",
        "absolute_or_traversal_paths",
    )
    return ModelCapabilityPolicy(
        schema="capability-v2",
        lane=decision.lane.value,
        risk=decision.risk.value,
        allowed_tools=allowed_tools,
        active_repository_ids=repositories,
        verification_passes=verification_passes,
        max_graph_depth=max_graph_depth,
        denied_by_default=denied,
        task_digest=task_scope_digest(task_text),
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
        task_digest=policy.task_digest,
    )


def authorize_model_action(
    policy: ModelCapabilityPolicy,
    request: ModelActionRequest,
    evidence: Sequence[ContextItem],
) -> AuthorizationDecision:
    """Authorize a model-proposed action without consulting model reasoning.

    The decision depends only on immutable control-plane policy, the structured
    requested action, and known evidence identities. Retrieved text, tool
    output, memory, and model-authored metadata never widen authority.
    """

    try:
        digest = action_request_digest(request)
    except _ParameterBudgetError:
        digest = "sha256:" + ("0" * 64)
        return _decision(
            policy,
            request,
            allowed=False,
            reason=DenialReason.PARAMETER_BUDGET_EXCEEDED.value,
            digest=digest,
        )
    except (TypeError, ValueError, RecursionError):
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
        if tool_name not in policy.allowed_tools:
            return _decision(
                policy,
                request,
                allowed=False,
                reason=DenialReason.TOOL_NOT_ALLOWLISTED.value,
                digest=digest,
            )

        if any(
            value is not None and str(value).strip()
            for value in (
                request.provider_id,
                request.network_host,
                request.secret_name,
                request.requested_lane,
            )
        ):
            return _decision(
                policy,
                request,
                allowed=False,
                reason=DenialReason.PRIVILEGED_PARAMETER.value,
                digest=digest,
            )

        repository_refs: set[str] = set()
        if request.repository_id is not None:
            repository_id = str(request.repository_id).strip()
            if (
                not repository_id
                or repository_id not in policy.active_repository_ids
            ):
                return _decision(
                    policy,
                    request,
                    allowed=False,
                    reason=DenialReason.REPOSITORY_SCOPE_VIOLATION.value,
                    digest=digest,
                )
            repository_refs.add(repository_id)

        parameter_reason, parameter_repositories = _validate_tool_parameters(
            policy,
            request.parameters,
        )
        if parameter_reason is not None:
            return _decision(
                policy,
                request,
                allowed=False,
                reason=parameter_reason,
                digest=digest,
            )
        repository_refs.update(parameter_repositories)

        if len(policy.active_repository_ids) > 1 and not repository_refs:
            return _decision(
                policy,
                request,
                allowed=False,
                reason=DenialReason.REPOSITORY_SCOPE_REQUIRED.value,
                digest=digest,
            )

        return _decision(
            policy,
            request,
            allowed=True,
            reason="preauthorized_scoped_tool",
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
