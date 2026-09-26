from __future__ import annotations

import math
from typing import Any

from .benchmark_protocol import context_item_file, normalize_file_path
from .models import ContextItem


ROLE_GAINS = {
    "edit_target": 2,
    "supporting_context": 1,
}


def role_aware_file_metrics(
    items: list[ContextItem],
    file_relevance: list[dict[str, Any]],
    distractor_files: list[str],
    k: int = 5,
) -> dict[str, Any] | None:
    if not file_relevance and not distractor_files:
        return None

    roles: dict[str, str] = {}
    for row in file_relevance:
        path = normalize_file_path(str(row.get("path", "")))
        role = str(row.get("role", "")).strip()
        if path and role in ROLE_GAINS:
            roles[path] = role

    distractors = {
        normalize_file_path(path)
        for path in distractor_files
        if str(path).strip()
    }

    cutoff = max(1, int(k))
    ranked_files: list[str] = []
    seen: set[str] = set()
    for item in items:
        path = context_item_file(item)
        if not path or path in seen:
            continue
        seen.add(path)
        ranked_files.append(path)
        if len(ranked_files) >= cutoff:
            break

    edit_targets = {
        path for path, role in roles.items() if role == "edit_target"
    }
    supporting_context = {
        path for path, role in roles.items() if role == "supporting_context"
    }
    relevant = set(roles)

    matched_edit = [path for path in ranked_files if path in edit_targets]
    matched_support = [
        path for path in ranked_files if path in supporting_context
    ]
    matched_relevant = [path for path in ranked_files if path in relevant]
    matched_distractors = [
        path for path in ranked_files if path in distractors
    ]

    edit_recall = (
        len(set(matched_edit)) / len(edit_targets)
        if edit_targets
        else None
    )
    support_recall = (
        len(set(matched_support)) / len(supporting_context)
        if supporting_context
        else None
    )

    first_edit = next(
        (
            rank
            for rank, path in enumerate(ranked_files, 1)
            if path in edit_targets
        ),
        None,
    )

    gains = [ROLE_GAINS.get(roles.get(path, ""), 0) for path in ranked_files]
    dcg = sum(
        (2**gain - 1) / math.log2(rank + 1)
        for rank, gain in enumerate(gains, 1)
        if gain > 0
    )
    ideal_gains = sorted(
        (ROLE_GAINS[role] for role in roles.values()),
        reverse=True,
    )[:cutoff]
    ideal_dcg = sum(
        (2**gain - 1) / math.log2(rank + 1)
        for rank, gain in enumerate(ideal_gains, 1)
    )

    weighted_total = sum(ROLE_GAINS[role] for role in roles.values())
    weighted_matched = sum(
        ROLE_GAINS[roles[path]]
        for path in set(matched_relevant)
    )

    return {
        "k": cutoff,
        "edit_target_files": sorted(edit_targets),
        "supporting_context_files": sorted(supporting_context),
        "known_distractor_files": sorted(distractors),
        "retrieved_files": ranked_files,
        "matched_edit_targets": matched_edit,
        "matched_supporting_context": matched_support,
        "matched_known_distractors": matched_distractors,
        "edit_target_recall_at_k": edit_recall,
        "supporting_context_recall_at_k": support_recall,
        "edit_target_mrr": (
            1.0 / first_edit if first_edit is not None else None
        ),
        "weighted_recall_at_k": (
            weighted_matched / weighted_total
            if weighted_total
            else None
        ),
        "graded_ndcg_at_k": (
            dcg / ideal_dcg if ideal_dcg else None
        ),
        "useful_precision_at_k": (
            len(set(matched_relevant)) / cutoff
            if relevant
            else None
        ),
        "known_distractor_rate_at_k": (
            len(set(matched_distractors)) / cutoff
            if distractors
            else None
        ),
        "coverage_balance": (
            min(edit_recall, support_recall)
            if edit_recall is not None
            and support_recall is not None
            else None
        ),
    }
