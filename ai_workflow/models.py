from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

from .evidence import EvidenceEnvelope


class Lane(str, Enum):
    ANSWER = "answer"
    SMALL = "small"
    FULL = "full"


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class RouteDecision:
    lane: Lane
    risk: Risk
    reasons: list[str] = field(default_factory=list)
    structural_context: bool = False
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["lane"] = self.lane.value
        d["risk"] = self.risk.value
        return d


@dataclass
class ContextItem:
    source: str
    text: str
    score: float = 0.0
    stale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence: EvidenceEnvelope | None = None

    @property
    def dedupe_key(self) -> str:
        canonical = " ".join(self.text.split()).encode("utf-8")
        return hashlib.blake2b(canonical, digest_size=20).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.evidence is not None:
            data["evidence"] = self.evidence.to_dict()
        return data
