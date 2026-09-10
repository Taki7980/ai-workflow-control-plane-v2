from __future__ import annotations

import math
from dataclasses import dataclass

from .budget import ContextBudget
from .workspace_selector import RepositorySelection


@dataclass(frozen=True)
class RepositoryBudget:
    repository_id: str
    rank: int
    ratio: float
    context: ContextBudget


def _allocate_integers(total: int, weighted: list[tuple[str, float]]) -> dict[str, int]:
    if total <= 0 or not weighted:
        return {key: 0 for key, _ in weighted}
    weight_sum = sum(max(0.0, weight) for _, weight in weighted)
    if weight_sum <= 0:
        return {key: 0 for key, _ in weighted}
    raw = [(key, total * max(0.0, weight) / weight_sum) for key, weight in weighted]
    allocated = {key: int(math.floor(value)) for key, value in raw}
    remainder = total - sum(allocated.values())
    order = [key for key, _ in weighted]
    for index in range(remainder):
        allocated[order[index % len(order)]] += 1
    return allocated


def _ratios(selections: list[RepositorySelection]) -> list[tuple[str, float]]:
    ordered = sorted(selections, key=lambda row: (row.rank, row.candidate.repository_id))
    positive = [(row.candidate.repository_id, max(0.0, float(row.score))) for row in ordered]
    total = sum(weight for _, weight in positive)
    if total <= 0:
        return []
    ratios = [(repo_id, weight / total) for repo_id, weight in positive]
    if len(ratios) > 1 and ratios[0][1] < 0.5:
        tail_total = sum(value for _, value in ratios[1:])
        tail = [
            (repo_id, 0.5 * value / tail_total if tail_total > 0 else 0.0)
            for repo_id, value in ratios[1:]
        ]
        ratios = [(ratios[0][0], 0.5), *tail]
    return ratios


def allocate_repository_budgets(
    parent: ContextBudget,
    selections: list[RepositorySelection],
) -> list[RepositoryBudget]:
    selected = sorted(
        (row for row in selections if row.selected and row.score > 0),
        key=lambda row: (row.rank, row.candidate.repository_id),
    )
    if not selected:
        selected = sorted(
            (row for row in selections if row.selected),
            key=lambda row: (row.rank, row.candidate.repository_id),
        )
    if not selected:
        return []
    if len(selected) == 1:
        row = selected[0]
        return [RepositoryBudget(row.candidate.repository_id, row.rank, 1.0, parent)]

    ratio_pairs = _ratios(selected)
    if not ratio_pairs:
        equal = 1.0 / len(selected)
        ratio_pairs = [(row.candidate.repository_id, equal) for row in selected]
    ratio_map = dict(ratio_pairs)
    weighted = [(row.candidate.repository_id, ratio_map[row.candidate.repository_id]) for row in selected]
    context_alloc = _allocate_integers(parent.context_chars, weighted)
    token_alloc = _allocate_integers(parent.estimated_tokens, weighted)
    source_alloc = {
        source: _allocate_integers(chars, weighted)
        for source, chars in parent.source_chars.items()
    }

    budgets: list[RepositoryBudget] = []
    for row in selected:
        repo_id = row.candidate.repository_id
        source_chars = {source: allocations[repo_id] for source, allocations in source_alloc.items()}
        budgets.append(
            RepositoryBudget(
                repository_id=repo_id,
                rank=row.rank,
                ratio=context_alloc[repo_id] / parent.context_chars if parent.context_chars else 0.0,
                context=ContextBudget(
                    estimated_tokens=token_alloc[repo_id],
                    output_tokens=0,
                    context_chars=context_alloc[repo_id],
                    source_chars=source_chars,
                ),
            )
        )
    return budgets
