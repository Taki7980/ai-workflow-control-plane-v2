"""Curated provider-domain API."""

from ..capability_gate import (
    AuthorizationDecision,
    Capability,
    DenialReason,
    ModelActionRequest,
    ModelCapabilityPolicy,
    authorize_model_action,
    build_model_capability_policy,
)
from ..provider_sandbox import (
    ResourceLimits,
    SandboxPlan,
    SandboxPolicy,
    SandboxUnavailableError,
    build_sandbox_plan,
)
from ..providers import ProviderStatus, detect, execution_provider, model_tier

__all__ = [
    "AuthorizationDecision",
    "Capability",
    "DenialReason",
    "ModelActionRequest",
    "ModelCapabilityPolicy",
    "ProviderStatus",
    "ResourceLimits",
    "SandboxPlan",
    "SandboxPolicy",
    "SandboxUnavailableError",
    "authorize_model_action",
    "build_model_capability_policy",
    "build_sandbox_plan",
    "detect",
    "execution_provider",
    "model_tier",
]
