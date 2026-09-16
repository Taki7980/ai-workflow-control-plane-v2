from __future__ import annotations

import heapq
from dataclasses import dataclass

from .math_retrieval import tokenize
from .models import ContextItem
from .token_estimator import CharacterTokenEstimator, TokenEstimator


@dataclass(frozen=True)
class _Candidate:
    item: ContextItem
    relevance: float
    tokens: frozenset[str]
    char_cost: int
    token_cost: int


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


def _candidates(
    query: str,
    items: list[ContextItem],
    estimator: TokenEstimator,
) -> list[_Candidate]:
    unique = _dedupe(items)
    if not unique:
        return []
    query_tokens = frozenset(tokenize(query))
    max_score = (
        max((max(0.0, float(item.score)) for item in unique), default=1.0)
        or 1.0
    )
    rows: list[_Candidate] = []
    for item in unique:
        tokens = frozenset(tokenize(item.text))
        lexical = _jaccard(query_tokens, tokens)
        source = max(0.0, float(item.score)) / max_score
        relevance = min(1.0, 0.65 * source + 0.35 * lexical)
        rows.append(
            _Candidate(
                item=item,
                relevance=relevance,
                tokens=tokens,
                char_cost=max(1, len(item.text)),
                token_cost=max(1, estimator.estimate(item.text)),
            )
        )
    return rows


def _active_cost(candidate: _Candidate, token_aware: bool) -> int:
    return candidate.token_cost if token_aware else candidate.char_cost


def _gain(
    candidate: _Candidate,
    universe: list[_Candidate],
    coverage: list[float],
) -> float:
    gain = 0.0
    for index, target in enumerate(universe):
        represented = target.relevance * _jaccard(target.tokens, candidate.tokens)
        if represented > coverage[index]:
            gain += represented - coverage[index]
    return gain


def _apply(
    candidate: _Candidate,
    universe: list[_Candidate],
    coverage: list[float],
) -> None:
    for index, target in enumerate(universe):
        represented = target.relevance * _jaccard(target.tokens, candidate.tokens)
        if represented > coverage[index]:
            coverage[index] = represented


def _bounded(
    rows: list[_Candidate],
    limit: int,
    mandatory_sources: tuple[str, ...],
    *,
    token_aware: bool,
) -> list[_Candidate]:
    if len(rows) <= limit:
        return rows
    mandatory = [row for row in rows if row.item.source in mandatory_sources]
    mandatory_keys = {row.item.dedupe_key for row in mandatory}
    ranked = sorted(
        (row for row in rows if row.item.dedupe_key not in mandatory_keys),
        key=lambda row: (
            -row.relevance,
            _active_cost(row, token_aware),
            row.item.source,
            row.item.dedupe_key,
        ),
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
    budget_tokens: int | None = None,
    token_estimator: TokenEstimator | None = None,
    max_selector_candidates: int | None = None,
) -> tuple[list[ContextItem], dict]:
    char_limit = max(
        0,
        int(budget_chars if budget_chars is not None else (char_budget or 0)),
    )
    token_limit = (
        None if budget_tokens is None else max(0, int(budget_tokens))
    )
    token_aware = token_limit is not None
    estimator = token_estimator or CharacterTokenEstimator()
    selector_cfg = (((config or {}).get("context") or {}).get("selector") or {})
    requested_limit = (
        max_selector_candidates
        if max_selector_candidates is not None
        else selector_cfg.get("max_selector_candidates", 200)
    )
    try:
        candidate_limit = max(1, int(requested_limit))
    except (TypeError, ValueError):
        candidate_limit = 200

    all_rows = _candidates(query, items, estimator)
    rows = _bounded(
        all_rows,
        candidate_limit,
        mandatory_sources,
        token_aware=token_aware,
    )
    if (
        not rows
        or char_limit <= 0
        or (token_aware and token_limit is not None and token_limit <= 0)
    ):
        return [], {
            "mode": "empty",
            "candidate_count": len(all_rows),
            "selector_candidates": len(rows),
            "candidate_limit": candidate_limit,
            "selected_count": 0,
            "used_chars": 0,
            "used_tokens": 0,
            "budget_chars": char_limit,
            "budget_tokens": token_limit,
        }

    selected: list[_Candidate] = []
    selected_keys: set[str] = set()
    used_chars = 0
    used_tokens = 0

    def fits(candidate: _Candidate) -> bool:
        if used_chars + candidate.char_cost > char_limit:
            return False
        if (
            token_aware
            and token_limit is not None
            and used_tokens + candidate.token_cost > token_limit
        ):
            return False
        return True

    def add(candidate: _Candidate) -> None:
        nonlocal used_chars, used_tokens
        selected.append(candidate)
        selected_keys.add(candidate.item.dedupe_key)
        used_chars += candidate.char_cost
        used_tokens += candidate.token_cost

    for candidate in rows:
        if candidate.item.source not in mandatory_sources:
            continue
        if candidate.item.dedupe_key in selected_keys or not fits(candidate):
            continue
        add(candidate)

    remaining_rows = [
        row for row in rows if row.item.dedupe_key not in selected_keys
    ]
    total_cost = sum(_active_cost(row, token_aware) for row in rows)
    active_budget = (
        token_limit
        if token_aware and token_limit is not None
        else char_limit
    )
    ratio = active_budget / max(1, total_cost)
    tight_fraction = float(selector_cfg.get("tight_budget_fraction", 0.3))

    if ratio <= tight_fraction:
        mode = "relevance"
        for candidate in sorted(
            remaining_rows,
            key=lambda row: (
                -row.relevance,
                _active_cost(row, token_aware),
                row.item.source,
                row.item.dedupe_key,
            ),
        ):
            if not fits(candidate):
                continue
            add(candidate)
    else:
        mode = "facility_location"
        coverage = [0.0] * len(rows)
        for candidate in selected:
            _apply(candidate, rows, coverage)
        heap: list[tuple[float, str, int, _Candidate]] = []
        epoch = 0
        for candidate in remaining_rows:
            cost = _active_cost(candidate, token_aware)
            score = _gain(candidate, rows, coverage) / cost
            heapq.heappush(
                heap,
                (-score, candidate.item.dedupe_key, epoch, candidate),
            )
        while heap:
            neg_bound, _, candidate_epoch, candidate = heapq.heappop(heap)
            if not fits(candidate):
                continue
            cost = _active_cost(candidate, token_aware)
            current = _gain(candidate, rows, coverage) / cost
            if candidate_epoch != epoch or abs(current + neg_bound) > 1e-12:
                heapq.heappush(
                    heap,
                    (-current, candidate.item.dedupe_key, epoch, candidate),
                )
                continue
            if current <= 0:
                break
            add(candidate)
            _apply(candidate, rows, coverage)
            epoch += 1

    result = [candidate.item for candidate in selected]
    return result, {
        "mode": mode,
        "candidate_count": len(all_rows),
        "selector_candidates": len(rows),
        "candidate_limit": candidate_limit,
        "selected_count": len(result),
        "used_chars": used_chars,
        "used_tokens": used_tokens,
        "budget_chars": char_limit,
        "budget_tokens": token_limit,
        "budget_ratio": round(ratio, 4),
        "mandatory_sources": list(mandatory_sources),
    }
