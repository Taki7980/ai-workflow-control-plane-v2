from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .repository_registry import (
    discover_repositories,
    load_registry,
    repository_id,
)
from .workspace import registry_spec_to_root


class EvidenceKind(str, Enum):
    """Broad, code-owned evidence categories exposed to downstream consumers."""

    INDEX = "index"
    REPOSITORY = "repository"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    TEST = "test"
    MEMORY = "memory"
    GENERATED = "generated"
    EXTERNAL = "external"
    CONTEXT = "context"


class EvidenceTrustClass(str, Enum):
    """Origin trust classes. Retrieved context is never an authority source."""

    UNTRUSTED_REPOSITORY_CONTENT = "untrusted_repository_content"
    UNTRUSTED_EXTERNAL_PROVIDER = "untrusted_external_provider"
    UNTRUSTED_DURABLE_MEMORY = "untrusted_durable_memory"
    UNTRUSTED_GENERATED_CONTEXT = "untrusted_generated_context"
    UNTRUSTED_CONTEXT_DATA = "untrusted_context_data"


@dataclass(frozen=True)
class EvidenceAuthority:
    """Capabilities that retrieved evidence is allowed to grant.

    PR-13 deliberately grants none. PR-14 can consume this typed contract at
    the deterministic action-authorization boundary.
    """

    instructions: bool = False
    tools: bool = False
    policy: bool = False
    repository_activation: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "instructions": self.instructions,
            "tools": self.tools,
            "policy": self.policy,
            "repository_activation": self.repository_activation,
        }


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Typed, content-bound identity for one exact downstream evidence item."""

    evidence_id: str
    repository_id: str
    kind: EvidenceKind
    content_sha256: str
    trust_class: EvidenceTrustClass
    authority: EvidenceAuthority = field(default_factory=EvidenceAuthority)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    confidence: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "repository_id": self.repository_id,
            "kind": self.kind.value,
            "content_sha256": self.content_sha256,
            "trust_class": self.trust_class.value,
            "authority": self.authority.to_dict(),
            "provenance": dict(self.provenance),
            "confidence": self.confidence,
        }


def evidence_kind_for_source(source: str) -> EvidenceKind:
    if source.startswith("external:"):
        return EvidenceKind.EXTERNAL
    if source == "lightweight_index":
        return EvidenceKind.INDEX
    if source == "targeted_source":
        return EvidenceKind.REPOSITORY
    if source in {"code_review_graph", "scip"}:
        return EvidenceKind.STRUCTURAL
    if source == "semantic":
        return EvidenceKind.SEMANTIC
    if source == "test_resolver":
        return EvidenceKind.TEST
    if source == "durable_memory":
        return EvidenceKind.MEMORY
    if source in {"hot_cache", "research_cache", "domain_manifest"}:
        return EvidenceKind.GENERATED
    return EvidenceKind.CONTEXT


def trust_class_for_source(source: str) -> EvidenceTrustClass:
    if source.startswith("external:"):
        return EvidenceTrustClass.UNTRUSTED_EXTERNAL_PROVIDER
    if source == "durable_memory":
        return EvidenceTrustClass.UNTRUSTED_DURABLE_MEMORY
    if source in {"hot_cache", "research_cache", "domain_manifest"}:
        return EvidenceTrustClass.UNTRUSTED_GENERATED_CONTEXT
    if source in {
        "lightweight_index",
        "targeted_source",
        "code_review_graph",
        "scip",
        "semantic",
        "test_resolver",
    }:
        return EvidenceTrustClass.UNTRUSTED_REPOSITORY_CONTENT
    return EvidenceTrustClass.UNTRUSTED_CONTEXT_DATA


def _safe_locator(metadata: Mapping[str, Any]) -> dict[str, Any]:
    locator: dict[str, Any] = {}
    for key in (
        "path",
        "file",
        "line",
        "start_line",
        "end_line",
        "symbol",
        "endpoint",
        "pattern",
        "role",
        "language",
    ):
        value = metadata.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            locator[key] = value
    return locator


def _content_sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_evidence_envelope(
    *,
    source: str,
    text: str,
    stale: bool,
    metadata: Mapping[str, Any],
    provenance: Mapping[str, Any],
    repository_id: str,
) -> EvidenceEnvelope:
    """Build a system-owned envelope without trusting caller authority claims."""

    kind = evidence_kind_for_source(source)
    trust_class = trust_class_for_source(source)
    content_sha256 = _content_sha256(text)
    locator = _safe_locator(metadata)
    raw_confidence = str(metadata.get("evidence_confidence") or "candidate").strip().casefold()
    confidence = raw_confidence if raw_confidence in {"candidate", "corroborated", "verified"} else "candidate"
    system_provenance: dict[str, Any] = {
        "retriever": source,
        "fresh": not stale,
    }
    if locator:
        system_provenance["locator"] = locator

    # Preserve only a bounded, informational provider label. It remains data,
    # never authority, and cannot override the system-owned fields above.
    provider = provenance.get("provider") or metadata.get("provider")
    if isinstance(provider, str) and provider.strip():
        system_provenance["provider"] = provider.strip()[:160]

    identity_payload = {
        "schema": "evidence-v1",
        "repository_id": repository_id,
        "source": source,
        "kind": kind.value,
        "content_sha256": content_sha256,
        "locator": locator,
    }
    digest = hashlib.sha256(
        json.dumps(
            identity_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return EvidenceEnvelope(
        evidence_id=f"evidence-v1:{digest}",
        repository_id=repository_id,
        kind=kind,
        content_sha256=content_sha256,
        trust_class=trust_class,
        authority=EvidenceAuthority(),
        provenance=system_provenance,
        confidence=confidence,
    )


def repository_ids_for_roots(
    control_root: Path,
    roots: list[Path],
    config: Mapping[str, Any] | None = None,
) -> dict[Path, str]:
    """Return stable, checkout-path-independent IDs for retrieval roots."""

    workspace = Path(control_root).resolve()
    resolved_roots = [Path(root).resolve() for root in roots]
    identities: dict[Path, str] = {}

    for spec in load_registry(workspace, dict(config or {})):
        try:
            candidate = registry_spec_to_root(workspace, spec)
        except (OSError, ValueError):
            continue
        candidate = candidate.resolve()
        if candidate in resolved_roots:
            identities[candidate] = repository_id(
                spec.relative_path,
                spec.remote_identity,
            )

    for candidate in resolved_roots:
        if candidate in identities:
            continue
        try:
            relative = candidate.relative_to(workspace).as_posix() or "."
        except ValueError:
            relative = f"legacy:{candidate.name.lower()}"

        remote_identity = None
        discovered = discover_repositories(candidate, max_depth=0)
        if discovered:
            remote_identity = discovered[0].remote_identity
        if relative.startswith("legacy:") and remote_identity:
            relative = f"legacy:{remote_identity}"

        identities[candidate] = repository_id(relative, remote_identity)

    return identities
