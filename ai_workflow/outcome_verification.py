from __future__ import annotations

import math
import os
from dataclasses import dataclass


TRUSTED_OUTCOME_SOURCES_ENV = "AI_WORKFLOW_TRUSTED_OUTCOME_SOURCES"
DEFAULT_TRUSTED_OUTCOME_SOURCES = frozenset(
    {
        "github-actions:test-suite",
        "github-actions:integration-suite",
        "signed-human-review",
        "local:test-suite",
    }
)


@dataclass(frozen=True)
class VerifiedOutcomeEvidence:
    source: str
    verifier_identity: str
    evidence_digest: str
    reward: float
    realized_cost: float


def trusted_outcome_sources() -> frozenset[str]:
    """Return trusted verifier source IDs from runtime-owned policy only.

    Repository configuration is intentionally not consulted here. Operators may
    extend the built-in set through a trusted process environment variable.
    """

    extra = {
        item.strip()
        for item in os.getenv(TRUSTED_OUTCOME_SOURCES_ENV, "").split(",")
        if item.strip()
    }
    return frozenset(set(DEFAULT_TRUSTED_OUTCOME_SOURCES) | extra)


def _validated_sha256_digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    prefix = "sha256:"
    if not digest.startswith(prefix):
        raise ValueError("immutable verifier evidence must use sha256:<hex>")
    hex_value = digest[len(prefix) :]
    if len(hex_value) != 64 or any(ch not in "0123456789abcdef" for ch in hex_value):
        raise ValueError("immutable verifier evidence must be a 64-byte sha256 hex digest")
    return digest


def validate_verified_outcome(
    *,
    source: str,
    verifier_identity: str,
    evidence_digest: str,
    reward: float,
    realized_cost: float,
) -> VerifiedOutcomeEvidence:
    source_id = str(source or "").strip()
    if source_id not in trusted_outcome_sources():
        raise ValueError("outcome source is not trusted by runtime policy")

    verifier = str(verifier_identity or "").strip()
    if not verifier:
        raise ValueError("verifier_identity must not be blank")

    reward_value = float(reward)
    cost_value = float(realized_cost)
    if not math.isfinite(reward_value) or not 0.0 <= reward_value <= 1.0:
        raise ValueError("reward must be finite and between 0.0 and 1.0")
    if not math.isfinite(cost_value) or cost_value < 0.0:
        raise ValueError("realized_cost must be finite and non-negative")

    return VerifiedOutcomeEvidence(
        source=source_id,
        verifier_identity=verifier,
        evidence_digest=_validated_sha256_digest(evidence_digest),
        reward=reward_value,
        realized_cost=cost_value,
    )
