from __future__ import annotations

import re
from dataclasses import dataclass

from .retrieval_policy import RetrievalPlan


@dataclass(frozen=True)
class TaskRetrievalPolicy:
    profile: str
    source_weight: float
    lexical_weight: float
    specialist_weight: float
    mmr_lambda: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "fusion_weights": {
                "source": self.source_weight,
                "lexical": self.lexical_weight,
                "specialist": self.specialist_weight,
            },
            "mmr_lambda": self.mmr_lambda,
            "reason": self.reason,
        }


_TRACE = re.compile(
    r"\b(traceback|stack trace|exception|panic|segfault|failed at|failure log|error log)\b",
    re.I,
)
_TEST = re.compile(
    r"\b(test|tests|pytest|unittest|spec|coverage|regression)\b",
    re.I,
)
_CHANGE = re.compile(
    r"\b(change|modify|refactor|rename|migration|impact|blast radius|what breaks|affected)\b",
    re.I,
)
_REVIEW = re.compile(
    r"\b(review|comment|feedback|requested change|nit|pull request|pr comment)\b",
    re.I,
)


def task_retrieval_policy(
    query: str,
    plan: RetrievalPlan,
    *,
    changed_files: list[str] | None = None,
) -> TaskRetrievalPolicy:
    """Return a deterministic task-conditioned fusion policy.

    Profiles mirror the workflow-signal families evaluated by Agent Retrieval
    Bench. They only change ranking/fusion weights; they cannot create provider,
    repository, graph, or capability authority.
    """

    text = " ".join(query.split())
    changed = bool(changed_files)

    if "tests_for" in plan.structural_patterns or (
        _TEST.search(text) and (_CHANGE.search(text) or changed)
    ):
        return TaskRetrievalPolicy(
            "code2test", 1.05, 1.15, 1.35, 0.78,
            "test discovery benefits from lexical anchors plus structural evidence",
        )
    if _TRACE.search(text):
        return TaskRetrievalPolicy(
            "trace2code", 1.10, 1.40, 1.15, 0.82,
            "failure traces contain high-value exact lexical anchors",
        )
    if "impact" in plan.structural_patterns or (
        changed and _CHANGE.search(text)
    ):
        return TaskRetrievalPolicy(
            "edit2ripple", 1.00, 0.85, 1.50, 0.72,
            "change-impact tasks prioritize dependency evidence",
        )
    if _REVIEW.search(text):
        return TaskRetrievalPolicy(
            "comment2context", 1.00, 1.05, 1.35, 0.76,
            "review comments often require semantic context beyond named files",
        )

    if plan.use_structural:
        return TaskRetrievalPolicy(
            "structural", 1.00, 0.85, 1.45, 0.72,
            "structural intent prioritizes graph-backed specialist evidence",
        )
    if plan.use_semantic:
        return TaskRetrievalPolicy(
            "semantic", 0.95, 1.00, 1.35, 0.76,
            "semantic intent prioritizes semantic specialist evidence",
        )
    return TaskRetrievalPolicy(
        "exact", 1.10, 1.35, 0.75, 0.84,
        "exact intent prioritizes deterministic lexical evidence",
    )
