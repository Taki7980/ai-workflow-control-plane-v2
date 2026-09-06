from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .math_retrieval import tokenize
from .models import ContextItem, Lane, RouteDecision


class RetrievalIntent(str, Enum):
    EXACT = "exact"
    SEMANTIC = "semantic"
    STRUCTURAL = "structural"
    MIXED = "mixed"


@dataclass(frozen=True)
class RetrievalPlan:
    intent: RetrievalIntent
    use_lexical: bool
    use_semantic: bool
    use_structural: bool
    reason: str


@dataclass(frozen=True)
class Sufficiency:
    score: float
    sufficient: bool
    lexical_coverage: float
    source_diversity: int
    exact_match: bool
    structural_complete: bool


_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_./-]+)?\b")
_PATH = re.compile(r"(?:[\w.-]+[/\\])+[\w.-]+")
_STRUCTURAL = re.compile(
    r"\b(caller|callee|call graph|dependency|dependents|impact|blast radius|what breaks|affected|tests for|execution flow|architecture)\b",
    re.I,
)
_SEMANTIC = re.compile(
    r"\b(where do we|how do we|how does|responsible for|handles?|prevents?|ensures?|implements?|logic for|flow for|behavior|behaviour|concept|meaning)\b",
    re.I,
)


def classify_retrieval_intent(
    query: str,
    decision: RouteDecision,
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
) -> RetrievalPlan:
    text = " ".join(query.strip().split())
    if decision.structural_context or _STRUCTURAL.search(text):
        return RetrievalPlan(RetrievalIntent.STRUCTURAL, True, False, True, "structural relationship requested")

    exact_signal = bool(symbol or endpoint or _PATH.search(text))
    if not exact_signal:
        tokens = _IDENTIFIER.findall(text)
        exact_signal = any("_" in token or any(c.isupper() for c in token[1:]) for token in tokens)

    semantic_signal = bool(_SEMANTIC.search(text)) or (len(tokenize(text)) >= 7 and not exact_signal)

    if exact_signal and semantic_signal:
        return RetrievalPlan(RetrievalIntent.MIXED, True, True, False, "identifier and semantic intent both present")
    if exact_signal:
        return RetrievalPlan(RetrievalIntent.EXACT, True, False, False, "exact identifier/path/endpoint signal")
    if semantic_signal:
        return RetrievalPlan(RetrievalIntent.SEMANTIC, True, True, False, "natural-language semantic intent")
    if decision.lane == Lane.ANSWER:
        return RetrievalPlan(RetrievalIntent.MIXED, True, True, False, "read-only query with ambiguous retrieval intent")
    return RetrievalPlan(RetrievalIntent.EXACT, True, False, False, "bounded deterministic default")


def evaluate_sufficiency(
    query: str,
    items: list[ContextItem],
    *,
    structural_required: bool = False,
    threshold: float = 0.72,
) -> Sufficiency:
    if not items:
        return Sufficiency(0.0, False, 0.0, 0, False, False)

    q_tokens = set(tokenize(query))
    matched: set[str] = set()
    exact_match = False
    sources: set[str] = set()
    structural_complete = not structural_required

    normalized_query = "".join(query.casefold().split())
    for item in items:
        sources.add(item.source)
        text_tokens = set(tokenize(item.text))
        matched.update(q_tokens & text_tokens)
        normalized_text = "".join(item.text.casefold().split())
        if normalized_query and normalized_query in normalized_text:
            exact_match = True
        if item.source == "code_review_graph":
            structural_complete = True

    coverage = len(matched) / max(1, len(q_tokens))
    diversity = len(sources)
    score = 0.58 * coverage + 0.17 * min(1.0, diversity / 2) + 0.15 * float(exact_match) + 0.10 * float(structural_complete)
    score = max(0.0, min(1.0, score))
    sufficient = score >= threshold and (structural_complete or not structural_required)
    return Sufficiency(round(score, 4), sufficient, round(coverage, 4), diversity, exact_match, structural_complete)
