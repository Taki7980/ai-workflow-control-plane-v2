from __future__ import annotations

from typing import TypedDict

from .models import Lane, Risk, RouteDecision
from .providers import ProviderStatus


class ComplexityVector(TypedDict):
    lane_weight: int
    risk_weight: int
    changed_file_count: int
    workspace_root_count: int
    structural_intent: bool
    evidence_gap: bool


class OrchestrationBudget(TypedDict):
    max_agent_slots: int
    max_crg_calls: int
    max_graph_depth: int
    review_passes: int
    verification_passes: int


class OrchestrationContract(TypedDict):
    complexity_vector: ComplexityVector
    complexity_score: int
    superpowers_skills: list[str]
    crg_plan: list[str]
    agent_slots: int
    review_passes: int
    verification_passes: int
    graph_depth: int
    budget: OrchestrationBudget
    native_fallback: bool


def _lane_weight(lane: Lane) -> int:
    return {Lane.ANSWER: 0, Lane.SMALL: 1, Lane.FULL: 2}[lane]


def _risk_weight(risk: Risk) -> int:
    return {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}[risk]


def _budget(config: dict) -> OrchestrationBudget:
    raw = ((config.get("execution") or {}).get("orchestration_budget") or {})
    return {
        "max_agent_slots": max(1, int(raw.get("max_agent_slots", 4))),
        "max_crg_calls": max(0, int(raw.get("max_crg_calls", 6))),
        "max_graph_depth": max(1, int(raw.get("max_graph_depth", 3))),
        "review_passes": max(1, int(raw.get("review_passes", 2))),
        "verification_passes": max(1, int(raw.get("verification_passes", 2))),
    }


def build_orchestration_contract(
    decision: RouteDecision,
    retrieval_diagnostics: dict,
    changed_files: list[str],
    workspace_count: int,
    providers: ProviderStatus,
    config: dict,
) -> OrchestrationContract:
    intent = str(retrieval_diagnostics.get("retrieval_intent", "unknown"))
    sufficient = bool((retrieval_diagnostics.get("sufficiency") or {}).get("sufficient", False))
    complexity: ComplexityVector = {
        "lane_weight": _lane_weight(decision.lane),
        "risk_weight": _risk_weight(decision.risk),
        "changed_file_count": len(changed_files),
        "workspace_root_count": max(1, int(workspace_count)),
        "structural_intent": intent == "structural" or bool(decision.structural_context),
        "evidence_gap": not sufficient,
    }
    score = (
        complexity["lane_weight"] * 2
        + complexity["risk_weight"] * 2
        + min(4, complexity["changed_file_count"])
        + min(2, complexity["workspace_root_count"] - 1)
        + (2 if complexity["structural_intent"] else 0)
        + (2 if complexity["evidence_gap"] else 0)
    )

    budget = _budget(config)
    if decision.lane == Lane.ANSWER:
        slots = 1
        skills: list[str] = []
        review_passes = 1
        verification_passes = 1
    elif decision.lane == Lane.SMALL:
        slots = 1
        skills = ["test-driven-development", "verification-before-completion"] if providers.superpowers else []
        review_passes = 1
        verification_passes = 1
    else:
        slots = min(budget["max_agent_slots"], 2 + int(score >= 8) + int(score >= 12))
        skills = (
            ["writing-plans", "subagent-driven-development", "requesting-code-review", "verification-before-completion"]
            if providers.superpowers else []
        )
        review_passes = min(budget["review_passes"], 1 + int(decision.risk == Risk.HIGH or score >= 10))
        verification_passes = min(budget["verification_passes"], 1 + int(decision.risk == Risk.HIGH or complexity["evidence_gap"]))

    crg_plan: list[str] = []
    if providers.code_review_graph and decision.lane != Lane.ANSWER:
        crg_plan.append("get_minimal_context_tool")
        if complexity["structural_intent"] or len(changed_files) >= 2:
            crg_plan.append("get_impact_radius_tool")
        if complexity["structural_intent"]:
            crg_plan.append("query_graph_tool")
        crg_plan.append("get_review_context_tool")
        crg_plan = crg_plan[: budget["max_crg_calls"]]

    return {
        "complexity_vector": complexity,
        "complexity_score": score,
        "superpowers_skills": skills,
        "crg_plan": crg_plan,
        "agent_slots": min(slots, budget["max_agent_slots"]),
        "review_passes": min(review_passes, budget["review_passes"]),
        "verification_passes": min(verification_passes, budget["verification_passes"]),
        "graph_depth": min(1 + int(score >= 8) + int(score >= 12), budget["max_graph_depth"]),
        "budget": budget,
        "native_fallback": decision.lane != Lane.ANSWER and not providers.superpowers,
    }
