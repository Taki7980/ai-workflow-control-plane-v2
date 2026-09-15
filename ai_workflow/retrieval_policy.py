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
    structural_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sufficiency:
    score: float
    sufficient: bool
    lexical_coverage: float
    source_diversity: int
    exact_match: bool
    structural_complete: bool


_IDENTIFIER = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_./-]+)?\b"
)
_PATH = re.compile(r"(?:[\w.-]+[/\\])+[\w.-]+")
_STRUCTURAL = re.compile(
    r"\b(caller|callee|call graph|dependency|dependents|impact|"
    r"blast radius|what breaks|affected|tests for|execution flow|"
    r"architecture)\b",
    re.I,
)
_SEMANTIC = re.compile(
    r"\b(where do we|how do we|how does|responsible for|handles?|"
    r"prevents?|ensures?|implements?|logic for|flow for|behavior|"
    r"behaviour|concept|meaning)\b",
    re.I,
)
_CALLERS = re.compile(
    r"\b(who\s+calls?|callers?|called\s+by|references?\s+to|dependents?)\b",
    re.I,
)
_CALLEES = re.compile(
    r"\b(callees?|what\s+does\b.*\bcall|calls?\s+into|"
    r"dependencies?|imports?\s+of)\b",
    re.I,
)
_TESTS = re.compile(
    r"\b(tests?\s+(?:for|cover|covering)|which\s+tests?|"
    r"test\s+coverage)\b",
    re.I,
)
_IMPACT = re.compile(
    r"\b(impact|blast\s+radius|what\s+breaks|affected)\b",
    re.I,
)
_ARCHITECTURE = re.compile(
    r"\b(architecture|execution\s+flow|call\s+graph)\b",
    re.I,
)


def structural_requirements(query: str) -> tuple[str, ...]:
    """Return the minimum CRG relationship evidence requested by *query*."""

    text = " ".join(query.strip().split())
    patterns: list[str] = []
    for pattern, matcher in (
        ("impact", _IMPACT),
        ("tests_for", _TESTS),
        ("callers_of", _CALLERS),
        ("callees_of", _CALLEES),
        ("architecture", _ARCHITECTURE),
    ):
        if matcher.search(text):
            patterns.append(pattern)
    return tuple(patterns)


def classify_retrieval_intent(
    query: str,
    decision: RouteDecision,
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
) -> RetrievalPlan:
    text = " ".join(query.strip().split())

    exact_signal = bool(symbol or endpoint or _PATH.search(text))
    if not exact_signal:
        tokens = _IDENTIFIER.findall(text)
        exact_signal = any(
            "_" in token
            or any(character.isupper() for character in token[1:])
            for token in tokens
        )

    semantic_signal = bool(_SEMANTIC.search(text)) or (
        len(tokenize(text)) >= 7 and not exact_signal
    )
    structural_patterns = structural_requirements(text)
    structural_signal = (
        decision.structural_context
        or bool(structural_patterns)
        or bool(_STRUCTURAL.search(text))
    )
    if structural_signal:
        if not structural_patterns:
            structural_patterns = ("architecture",)
        use_semantic = not exact_signal
        intent = (
            RetrievalIntent.MIXED
            if use_semantic
            else RetrievalIntent.STRUCTURAL
        )
        reason = (
            "structural relationship needs entry-point discovery"
            if use_semantic
            else "structural relationship requested"
        )
        return RetrievalPlan(
            intent,
            True,
            use_semantic,
            True,
            reason,
            structural_patterns,
        )

    if exact_signal and semantic_signal:
        return RetrievalPlan(
            RetrievalIntent.MIXED,
            True,
            True,
            False,
            "identifier and semantic intent both present",
        )
    if exact_signal:
        return RetrievalPlan(
            RetrievalIntent.EXACT,
            True,
            False,
            False,
            "exact identifier/path/endpoint signal",
        )
    if semantic_signal:
        return RetrievalPlan(
            RetrievalIntent.SEMANTIC,
            True,
            True,
            False,
            "natural-language semantic intent",
        )
    if decision.lane == Lane.ANSWER:
        return RetrievalPlan(
            RetrievalIntent.MIXED,
            True,
            True,
            False,
            "read-only query with ambiguous retrieval intent",
        )
    return RetrievalPlan(
        RetrievalIntent.EXACT,
        True,
        False,
        False,
        "bounded deterministic default",
    )


def evaluate_sufficiency(
    query: str,
    items: list[ContextItem],
    *,
    structural_required: bool = False,
    structural_patterns: tuple[str, ...] = (),
    threshold: float = 0.72,
) -> Sufficiency:
    if not items:
        return Sufficiency(0.0, False, 0.0, 0, False, False)

    q_tokens = set(tokenize(query))
    matched: set[str] = set()
    exact_match = False
    sources: set[str] = set()
    matched_structural: set[str] = set()

    normalized_query = "".join(query.casefold().split())
    for item in items:
        sources.add(item.source)
        text_tokens = set(tokenize(item.text))
        matched.update(q_tokens & text_tokens)
        normalized_text = "".join(item.text.casefold().split())
        if normalized_query and normalized_query in normalized_text:
            exact_match = True

        if (
            item.source == "code_review_graph"
            and bool(item.metadata.get("structural_valid"))
        ):
            pattern = str(item.metadata.get("pattern") or "").strip()
            if pattern:
                matched_structural.add(pattern)

    if not structural_required:
        structural_complete = True
    elif structural_patterns:
        structural_complete = set(structural_patterns).issubset(
            matched_structural
        )
    else:
        structural_complete = bool(matched_structural)

    coverage = len(matched) / max(1, len(q_tokens))
    diversity = len(sources)
    score = (
        0.58 * coverage
        + 0.17 * min(1.0, diversity / 2)
        + 0.15 * float(exact_match)
        + 0.10 * float(structural_complete)
    )
    score = max(0.0, min(1.0, score))
    sufficient = score >= threshold and (
        structural_complete or not structural_required
    )
    return Sufficiency(
        round(score, 4),
        sufficient,
        round(coverage, 4),
        diversity,
        exact_match,
        structural_complete,
    )
