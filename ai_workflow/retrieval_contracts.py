from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .models import ContextItem


@dataclass(frozen=True)
class RetrievalRequest:
    """Stable request boundary shared by retrieval providers."""

    query: str
    root: Path
    limit: int
    intent: str = "mixed"
    timeout_seconds: float = 8.0
    changed_files: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("retrieval query must not be blank")
        if int(self.limit) < 1:
            raise ValueError("retrieval limit must be >= 1")
        if float(self.timeout_seconds) <= 0:
            raise ValueError("retrieval timeout_seconds must be > 0")


@dataclass(frozen=True)
class ProviderResult:
    """Typed provider result that separates evidence from provider failures."""

    provider: str
    items: tuple[ContextItem, ...] = ()
    latency_ms: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    timed_out: bool = False
    output_limited: bool = False
    returncode: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def error_dict(self) -> dict[str, Any] | None:
        if self.error is None:
            return None
        return {
            "kind": self.error_kind or "provider_error",
            "message": self.error,
            "timed_out": self.timed_out,
            "output_limited": self.output_limited,
            "returncode": self.returncode,
        }


class Retriever(Protocol):
    """Synchronous provider contract."""

    name: str

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        ...


class AsyncRetriever(Protocol):
    """Native asynchronous provider contract with identical result semantics."""

    name: str

    async def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        ...
