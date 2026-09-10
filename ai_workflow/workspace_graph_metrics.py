from __future__ import annotations

from .models import ContextItem


def _gold(values: list[str]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def _ranked_graph_items(
    items: list[ContextItem],
    k: int,
) -> list[ContextItem]:
    return [
        item
        for item in items[: max(1, int(k))]
        if item.source == "workspace_graph"
    ]


def _observed_edges(items: list[ContextItem], k: int) -> set[str]:
    observed: set[str] = set()
    for item in _ranked_graph_items(items, k):
        raw = item.metadata.get("graph_edge_ids") or []
        if isinstance(raw, (list, tuple, set)):
            observed.update(str(value) for value in raw if str(value))
    return observed


def graph_node_recall_at_k(
    items: list[ContextItem],
    gold_nodes: list[str],
    k: int = 5,
) -> float | None:
    gold = _gold(gold_nodes)
    if not gold:
        return None
    observed = {
        str(item.metadata.get("graph_node_id"))
        for item in _ranked_graph_items(items, k)
        if item.metadata.get("graph_node_id")
    }
    return len(gold & observed) / len(gold)


def cross_repo_edge_recall(
    items: list[ContextItem],
    gold_edges: list[str],
    k: int = 5,
) -> float | None:
    gold = _gold(gold_edges)
    if not gold:
        return None
    observed = _observed_edges(items, k)
    return len(gold & observed) / len(gold)


def wrong_edge_rate(
    items: list[ContextItem],
    gold_edges: list[str],
    k: int = 5,
) -> float | None:
    gold = _gold(gold_edges)
    if not gold:
        return None
    observed = _observed_edges(items, k)
    if not observed:
        return 0.0
    return len(observed - gold) / len(observed)


def structural_recall_at_k(
    items: list[ContextItem],
    gold_evidence: list[str],
    k: int = 5,
) -> float | None:
    patterns = {
        str(value).strip().casefold()
        for value in gold_evidence
        if str(value).strip()
    }
    if not patterns:
        return None
    texts = [
        item.text.casefold()
        for item in _ranked_graph_items(items, k)
    ]
    covered = sum(
        any(pattern in text for text in texts)
        for pattern in patterns
    )
    return covered / len(patterns)


def graph_context_yield(
    items: list[ContextItem],
    gold_evidence: list[str],
    k: int = 5,
) -> float | None:
    patterns = {
        str(value).strip().casefold()
        for value in gold_evidence
        if str(value).strip()
    }
    if not patterns:
        return None
    ranked = _ranked_graph_items(items, k)
    delivered = sum(len(item.text) for item in ranked)
    if delivered <= 0:
        return 0.0
    useful = sum(
        len(item.text)
        for item in ranked
        if any(pattern in item.text.casefold() for pattern in patterns)
    )
    return useful / delivered
