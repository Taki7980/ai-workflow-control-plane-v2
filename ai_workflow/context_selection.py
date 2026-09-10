from __future__ import annotations

import heapq
from dataclasses import dataclass

from .math_retrieval import tokenize
from .models import ContextItem


@dataclass(frozen=True)
class _Candidate:
    item: ContextItem
    relevance: float
    terms: frozenset[str]
    cost: int


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _dedupe(items: list[ContextItem]) -> list[ContextItem]:
    out: list[ContextItem] = []
    seen: set[str] = set()
    for item in items:
        key = item.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _candidates(query: str, items: list[ContextItem]) -> list[_Candidate]:
    unique = _dedupe(items)
    if not unique:
        return []
    query_terms = frozenset(tokenize(query))
    max_score = max((max(0.0, float(item.score)) for item in unique), default=1.0) or 1.0
    rows = []
    for item in unique:
        terms = frozenset(tokenize(item.text))
        lexical = _jaccard(query_terms, terms)
        source = max(0.0, float(item.score)) / max_score
        relevance = min(1.0, 0.65 * source + 0.35 * lexical)
        rows.append(_Candidate(item, relevance, terms, max(1, len(item.text))))
    return rows


def _gain(candidate: _Candidate, universe: list[_Candidate], coverage: list[float]) -> float:
    gain = 0.0
    for index, target in enumerate(universe):
        represented = target.relevance * _jaccard(target.terms, candidate.terms)
        if represented > coverage[index]:
            gain += represented - coverage[index]
    return gain


def _apply(candidate: _Candidate, universe: list[_Candidate], coverage: list[float]) -> None:
    for index, target in enumerate(universe):
        represented = target.relevance * _jaccard(target.terms, candidate.terms)
        if represented > coverage[index]:
            coverage[index] = represented


def _bounded(rows: list[_Candidate], limit: int, mandatory_sources: tuple[str, ...]) -> list[_Candidate]:
    if len(rows) <= limit:
        return rows
    mandatory = [row for row in rows if row.item.source in mandatory_sources]
    mandatory_keys = {row.item.dedupe_key for row in mandatory}
    ranked = sorted(
        (row for row in rows if row.item.dedupe_key not in mandatory_keys),
        key=lambda c: (-c.relevance, c.cost, c.item.source, c.item.dedupe_key),
    )
    return mandatory + ranked[: max(0, limit - len(mandatory))]


def select_context(
    query: str,
    items: list[ContextItem],
    char_budget: int | None = None,
    config: dict | None = None,
    *,
    mandatory_sources: tuple[str, ...] = (),
    budget_chars: int | None = None,
    max_selector_candidates: int | None = None,
) -> tuple[list[ContextItem], dict]:
    budget = max(0, int(budget_chars if budget_chars is not None else (char_budget or 0)))
    selector_cfg = (((config or {}).get("context") or {}).get("selector") or {})
    requested_limit = max_selector_candidates if max_selector_candidates is not None else selector_cfg.get("max_selector_candidates", 200)
    try:
        candidate_limit = max(1, int(requested_limit))
    except (TypeError, ValueError):
        candidate_limit = 200
    all_rows = _candidates(query, items)
    rows = _bounded(all_rows, candidate_limit, mandatory_sources)
    if not rows or budget <= 0:
        return [], {
            "mode": "empty", "candidate_count": len(all_rows), "selector_candidates": len(rows),
            "selected_count": 0, "used_chars": 0,
        }

    selected: list[_Candidate] = []
    selected_keys: set[str] = set()
    used = 0

    for candidate in rows:
        if candidate.item.source not in mandatory_sources:
            continue
        if candidate.item.dedupe_key in selected_keys or used + candidate.cost > budget:
            continue
        selected.append(candidate); selected_keys.add(candidate.item.dedupe_key); used += candidate.cost

    remaining_rows = [row for row in rows if row.item.dedupe_key not in selected_keys]
    total_cost = sum(row.cost for row in rows)
    ratio = budget / max(1, total_cost)
    tight_fraction = float(selector_cfg.get("tight_budget_fraction", 0.3))

    if ratio <= tight_fraction:
        mode = "relevance"
        for candidate in sorted(remaining_rows, key=lambda c: (-c.relevance, c.cost, c.item.source, c.item.dedupe_key)):
            if used + candidate.cost > budget:
                continue
            selected.append(candidate); selected_keys.add(candidate.item.dedupe_key); used += candidate.cost
    else:
        mode = "facility_location"
        coverage = [0.0] * len(rows)
        for candidate in selected:
            _apply(candidate, rows, coverage)
        heap: list[tuple[float, str, int, _Candidate]] = []
        epoch = 0
        for candidate in remaining_rows:
            score = _gain(candidate, rows, coverage) / candidate.cost
            heapq.heappush(heap, (-score, candidate.item.dedupe_key, epoch, candidate))
        while heap:
            neg_bound, _, candidate_epoch, candidate = heapq.heappop(heap)
            if used + candidate.cost > budget:
                continue
            current = _gain(candidate, rows, coverage) / candidate.cost
            if candidate_epoch != epoch or abs(current + neg_bound) > 1e-12:
                heapq.heappush(heap, (-current, candidate.item.dedupe_key, epoch, candidate)); continue
            if current <= 0:
                break
            selected.append(candidate); selected_keys.add(candidate.item.dedupe_key); used += candidate.cost
            _apply(candidate, rows, coverage); epoch += 1

    result = [candidate.item for candidate in selected]
    return result, {
        "mode": mode,
        "candidate_count": len(all_rows),
        "selector_candidates": len(rows),
        "candidate_limit": candidate_limit,
        "selected_count": len(result),
        "used_chars": used,
        "budget_chars": budget,
        "budget_ratio": round(ratio, 4),
        "mandatory_sources": list(mandatory_sources),
    }
