from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TokenEstimator(Protocol):
    def estimate(self, text: str) -> int: ...


@dataclass(frozen=True)
class CharacterTokenEstimator:
    """Honest provider-neutral estimate; integrations may supply real tokenizers."""

    chars_per_token: int = 4

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        divisor = max(1, int(self.chars_per_token))
        return max(1, (len(text) + divisor - 1) // divisor)
