from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSemantics:
    """Execution properties that must be explicit before reuse or caching."""

    deterministic: bool = False
    cacheable: bool = False
    idempotent: bool = True
    side_effecting: bool = False
    retryable: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> ProviderSemantics:
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ValueError("provider semantics must be an object")

        def flag(name: str, default: bool) -> bool:
            value = raw.get(name, default)
            if not isinstance(value, bool):
                raise ValueError(f"provider semantics.{name} must be boolean")
            return value

        return cls(
            deterministic=flag("deterministic", False),
            cacheable=flag("cacheable", False),
            idempotent=flag("idempotent", True),
            side_effecting=flag("side_effecting", False),
            retryable=flag("retryable", True),
        )


def cache_eligible(semantics: ProviderSemantics) -> bool:
    """Return true only for explicitly deterministic, non-mutating providers."""

    return bool(
        semantics.deterministic
        and semantics.cacheable
        and not semantics.side_effecting
    )
