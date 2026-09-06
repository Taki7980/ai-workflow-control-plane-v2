from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

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

    @property
    def dedupe_key(self) -> str:
        return "".join(self.text.split())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
