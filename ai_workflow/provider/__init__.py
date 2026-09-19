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
from ..providers import ProviderStatus, detect, execution_provider, model_tier

__all__ = [
    "AuthorizationDecision",
    "Capability",
    "DenialReason",
    "ModelActionRequest",
    "ModelCapabilityPolicy",
    "ProviderStatus",
    "authorize_model_action",
    "build_model_capability_policy",
    "detect",
    "execution_provider",
    "model_tier",
]
