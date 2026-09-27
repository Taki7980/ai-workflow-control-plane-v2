from __future__ import annotations

from typing import Any

from .benchmark_protocol import context_item_file, normalize_file_path
from .config import estimate_tokens
from .models import ContextItem


def _estimated_tokens(items: list[ContextItem]) -> int:
    return sum(estimate_tokens(item.text) for item in items)


def _dedupe(items: list[ContextItem]) -> list[ContextItem]:
    out: list[ContextItem] = []
    seen: set[str] = set()
    for item in items:
        if item.dedupe_key in seen:
            continue
        seen.add(item.dedupe_key)
        out.append(item)
    return out


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def retrieval_token_funnel(
    retrieved_items: list[ContextItem],
    ranked_items: list[ContextItem],
    selected_items: list[ContextItem],
    *,
    hard_budget_tokens: int,
    adaptive_budget_tokens: int,
    retrieval_call_count: int,
) -> dict[str, Any]:
    unique_retrieved = _dedupe(retrieved_items)

    retrieved_tokens = _estimated_tokens(retrieved_items)
    unique_tokens = _estimated_tokens(unique_retrieved)
    ranked_tokens = _estimated_tokens(ranked_items)
    selected_tokens = _estimated_tokens(selected_items)

    duplicate_tokens = max(0, retrieved_tokens - unique_tokens)
    duplicate_items = max(0, len(retrieved_items) - len(unique_retrieved))

    return {
        "estimator": "provider_neutral_estimate",
        "retrieved_item_count": len(retrieved_items),
        "retrieved_estimated_tokens": retrieved_tokens,
        "unique_retrieved_item_count": len(unique_retrieved),
        "unique_retrieved_estimated_tokens": unique_tokens,
        "duplicate_item_count": duplicate_items,
        "duplicate_estimated_tokens": duplicate_tokens,
        "duplicate_token_fraction": _ratio(
            duplicate_tokens,
            retrieved_tokens,
        ),
        "ranked_candidate_item_count": len(ranked_items),
        "ranked_candidate_estimated_tokens": ranked_tokens,
        "selected_item_count": len(selected_items),
        "selected_estimated_tokens": selected_tokens,
        "selected_vs_retrieved_token_ratio": _ratio(
            selected_tokens,
            retrieved_tokens,
        ),
        "selected_vs_ranked_token_ratio": _ratio(
            selected_tokens,
            ranked_tokens,
        ),
        "estimated_token_reduction_vs_retrieved": (
            round(1.0 - (selected_tokens / retrieved_tokens), 4)
            if retrieved_tokens > 0
            else None
        ),
        "hard_budget_tokens": max(0, int(hard_budget_tokens)),
        "adaptive_budget_tokens": max(0, int(adaptive_budget_tokens)),
        "selected_hard_budget_utilization": _ratio(
            selected_tokens,
            max(0, int(hard_budget_tokens)),
        ),
        "selected_adaptive_budget_utilization": _ratio(
            selected_tokens,
            max(0, int(adaptive_budget_tokens)),
        ),
        "adaptive_budget_fraction": _ratio(
            max(0, int(adaptive_budget_tokens)),
            max(0, int(hard_budget_tokens)),
        ),
        "retrieval_call_count": max(0, int(retrieval_call_count)),
    }


def benchmark_token_economics(
    selected_items: list[ContextItem],
    case: dict[str, Any],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    funnel = dict(diagnostics.get("token_funnel") or {})
    total_selected = int(
        funnel.get(
            "selected_estimated_tokens",
            _estimated_tokens(selected_items),
        )
        or 0
    )

    gold = {
        normalize_file_path(path)
        for path in case.get("gold_files") or []
        if isinstance(path, str) and path.strip()
    }
    distractors = {
        normalize_file_path(path)
        for path in case.get("distractor_files") or []
        if isinstance(path, str) and path.strip()
    }
    roles = {
        normalize_file_path(str(row.get("path", ""))): str(
            row.get("role", "")
        ).strip()
        for row in case.get("file_relevance") or []
        if isinstance(row, dict) and str(row.get("path", "")).strip()
    }

    gold_tokens = 0
    edit_tokens = 0
    support_tokens = 0
    distractor_tokens = 0

    for item in selected_items:
        path = context_item_file(item)
        if path is None:
            continue
        tokens = estimate_tokens(item.text)
        if path in gold:
            gold_tokens += tokens
        if roles.get(path) == "edit_target":
            edit_tokens += tokens
        elif roles.get(path) == "supporting_context":
            support_tokens += tokens
        if path in distractors:
            distractor_tokens += tokens

    attributed = min(
        total_selected,
        gold_tokens + distractor_tokens,
    )
    unattributed = max(0, total_selected - attributed)
    retrieved_tokens = int(funnel.get("retrieved_estimated_tokens", 0) or 0)

    return {
        **funnel,
        "selected_gold_file_estimated_tokens": gold_tokens,
        "selected_edit_target_estimated_tokens": edit_tokens,
        "selected_supporting_context_estimated_tokens": support_tokens,
        "selected_known_distractor_estimated_tokens": distractor_tokens,
        "selected_unattributed_estimated_tokens": unattributed,
        "gold_file_token_share": _ratio(gold_tokens, total_selected),
        "edit_target_token_share": _ratio(edit_tokens, total_selected),
        "supporting_context_token_share": _ratio(
            support_tokens,
            total_selected,
        ),
        "known_distractor_token_share": _ratio(
            distractor_tokens,
            total_selected,
        ),
        "unattributed_token_share": _ratio(
            unattributed,
            total_selected,
        ),
        "gold_file_tokens_per_1k_retrieved": (
            round(gold_tokens * 1000 / retrieved_tokens, 4)
            if retrieved_tokens > 0
            else None
        ),
        "latency_ms": (
            (diagnostics.get("scheduler") or {}).get("elapsed_ms")
        ),
    }
