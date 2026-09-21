from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import ContextItem
from .retrieval_policy import Sufficiency


class EvidenceCondition(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    IRRELEVANT = "irrelevant"
    NO_CONTEXT = "no_context"
    CONFLICTING = "conflicting"
    WRONG_REPOSITORY = "wrong_repository"


@dataclass(frozen=True)
class SelectiveRetrievalDecision:
    condition: EvidenceCondition
    accept: bool
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "condition": self.condition.value,
            "accept": self.accept,
            "score": self.score,
            "reasons": list(self.reasons),
        }


def _structural_conflict(items: list[ContextItem]) -> bool:
    """Detect a narrow, code-owned contradiction we can prove deterministically."""

    states: dict[tuple[str, str], set[str]] = {}
    for item in items:
        if not bool(item.metadata.get("structural_valid")):
            continue
        pattern = str(item.metadata.get("pattern") or "").strip()
        symbol = str(
            item.metadata.get("symbol")
            or item.metadata.get("qualified_name")
            or ""
        ).strip()
        if not pattern:
            continue
        key = (pattern, symbol)
        state = "empty" if bool(item.metadata.get("empty_verified")) else "present"
        states.setdefault(key, set()).add(state)
    return any(len(values) > 1 for values in states.values())


def evaluate_selective_retrieval(
    items: list[ContextItem],
    sufficiency: Sufficiency,
    *,
    expected_repository_ids: set[str] | None = None,
    minimum_coverage: float = 0.15,
) -> SelectiveRetrievalDecision:
    """Apply deterministic evidence-quality gates after retrieval.

    Retriever/model scores are evidence, not authority. Acceptance requires the
    existing sufficiency contract plus basic quality checks. Ambiguous cases
    fail closed so the workflow can abstain or continue exploration.
    """

    if not items:
        return SelectiveRetrievalDecision(
            EvidenceCondition.NO_CONTEXT, False, 0.0, ("no_selected_context",)
        )

    reasons: list[str] = []
    expected = expected_repository_ids or set()
    if expected:
        observed = {
            item.evidence.repository_id
            for item in items
            if item.evidence is not None
        }
        if observed and not observed.issubset(expected):
            return SelectiveRetrievalDecision(
                EvidenceCondition.WRONG_REPOSITORY,
                False,
                0.0,
                ("evidence_repository_outside_routing_plan",),
            )

    if _structural_conflict(items):
        return SelectiveRetrievalDecision(
            EvidenceCondition.CONFLICTING,
            False,
            0.0,
            ("verified_structural_evidence_conflicts",),
        )

    fresh = [item for item in items if not item.stale]
    if not fresh:
        return SelectiveRetrievalDecision(
            EvidenceCondition.IRRELEVANT,
            False,
            0.0,
            ("all_selected_evidence_is_stale",),
        )

    if not sufficiency.structural_complete:
        reasons.append("required_structural_evidence_incomplete")
    if sufficiency.lexical_coverage < minimum_coverage:
        reasons.append("query_coverage_below_floor")
    if not sufficiency.sufficient:
        reasons.append("sufficiency_below_threshold")

    if reasons:
        condition = (
            EvidenceCondition.IRRELEVANT
            if sufficiency.lexical_coverage < minimum_coverage
            else EvidenceCondition.PARTIAL
        )
        return SelectiveRetrievalDecision(
            condition,
            False,
            sufficiency.score,
            tuple(reasons),
        )

    return SelectiveRetrievalDecision(
        EvidenceCondition.SUPPORTED,
        True,
        sufficiency.score,
        ("evidence_quality_gate_passed",),
    )
