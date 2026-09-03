from __future__ import annotations
from dataclasses import dataclass
from .models import Lane

@dataclass(frozen=True)
class ContextBudget:
    estimated_tokens: int
    output_tokens: int
    context_chars: int
    source_chars: dict[str, int]

def budget_for(lane: Lane, config: dict) -> ContextBudget:
    raw = config["budgets"][lane.value]
    total = int(raw["estimated_tokens"])
    shares = config["context"]["source_shares"]
    context_chars = total * 4
    source_chars = {name: max(160, int(context_chars * float(share))) for name, share in shares.items()}
    return ContextBudget(total, int(raw["output_tokens"]), context_chars, source_chars)

def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    if max_chars < 80:
        return text[:max_chars], True
    tail = min(220, max_chars // 5)
    head = max_chars - tail - 40
    return text[:head].rstrip() + "\n... [TRUNCATED] ...\n" + text[-tail:].lstrip(), True
