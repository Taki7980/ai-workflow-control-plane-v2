from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from .budget import truncate
from .math_retrieval import tokenize
from .models import ContextItem
from .workspace_graph import GraphEdge, GraphNode, WorkspaceGraph


@dataclass(frozen=True)
class GraphRetrievalResult:
    items: tuple[ContextItem, ...]
    diagnostics: dict[str, Any]


_DEFAULT_GRAPH_CONFIG = {
    "enabled": True,
    "max_hops": 2,
    "max_nodes": 24,
    "max_edges": 40,
    "max_context_chars": 3000,
    "min_edge_confidence": 0.8,
    "build_on_demand": True,
}


def _config(config: dict | None) -> dict[str, Any]:
    raw = (((config or {}).get("workspace") or {}).get("graph") or {})
    merged = dict(_DEFAULT_GRAPH_CONFIG)
    if isinstance(raw, dict):
        merged.update(raw)
    return merged


def _tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if len(token) > 1}


def _node_text(node: GraphNode) -> str:
    return " ".join(
        part
        for part in (
            node.kind,
            node.repository_path,
            node.path,
            node.symbol,
            node.label,
        )
        if part
    )


def _portable_candidates(node: GraphNode) -> tuple[str, ...]:
    values = [node.path.replace("\\", "/").lstrip("./")]
    if node.repository_path != ".":
        values.append(
            f"{node.repository_path.rstrip('/')}/{values[0]}".lstrip("/")
        )
    return tuple(value for value in values if value)


def _seed_nodes(
    nodes: tuple[GraphNode, ...],
    selected_repository_ids: set[str],
    *,
    symbol: str | None,
    endpoint: str | None,
    changed_files: tuple[str, ...],
    seed_items: tuple[ContextItem, ...],
) -> tuple[GraphNode, ...]:
    allowed = [
        node for node in nodes if node.repository_id in selected_repository_ids
    ]
    found: dict[str, tuple[int, GraphNode]] = {}

    def add(node: GraphNode, priority: int) -> None:
        current = found.get(node.node_id)
        if current is None or priority < current[0]:
            found[node.node_id] = (priority, node)

    if symbol:
        expected = symbol.casefold()
        for node in allowed:
            if node.symbol and node.symbol.casefold() == expected:
                add(node, 0)

    if endpoint:
        expected = endpoint.casefold()
        for node in allowed:
            if (
                node.kind == "endpoint"
                and (
                    node.symbol.casefold() == expected
                    or node.label.casefold() == expected
                )
            ):
                add(node, 0)

    for item in seed_items:
        repository_id = str(
            item.metadata.get("repository_id")
            or item.provenance.get("repository_id")
            or ""
        )
        if repository_id not in selected_repository_ids:
            continue
        candidate_path = str(
            item.metadata.get("file")
            or item.metadata.get("path")
            or item.provenance.get("file")
            or item.provenance.get("path")
            or ""
        ).replace("\\", "/").lstrip("./")
        if not candidate_path:
            continue
        for node in allowed:
            if node.repository_id != repository_id:
                continue
            if candidate_path in _portable_candidates(node):
                add(node, 1)

    normalized_changed = {
        str(path).replace("\\", "/").lstrip("/")
        for path in changed_files
        if str(path).strip()
    }
    if normalized_changed:
        for node in allowed:
            if any(
                candidate in normalized_changed
                for candidate in _portable_candidates(node)
            ):
                add(node, 2)

    if not found:
        for node in allowed:
            if node.kind == "repository":
                add(node, 3)

    return tuple(
        node
        for _, node in sorted(
            found.values(),
            key=lambda pair: (
                pair[0],
                pair[1].repository_id,
                pair[1].kind,
                pair[1].path,
                pair[1].node_id,
            ),
        )
    )


def _score(
    node: GraphNode,
    *,
    query_tokens: set[str],
    distance: int,
    seed: bool,
    changed: bool,
    cross_repo: bool,
    edge_confidence: float,
) -> float:
    query_overlap = len(query_tokens & _tokens(_node_text(node)))
    return (
        4.0 * query_overlap
        + 3.0 * int(seed)
        + 2.0 * int(changed)
        + 2.0 * int(cross_repo)
        + edge_confidence
        - 1.5 * distance
    )


def retrieve_workspace_graph(
    graph: WorkspaceGraph,
    query: str,
    selected_repository_ids: set[str],
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: tuple[str, ...] = (),
    seed_items: tuple[ContextItem, ...] = (),
    graph_fingerprint: str = "",
    config: dict | None = None,
) -> GraphRetrievalResult:
    cfg = _config(config)
    if not bool(cfg.get("enabled", True)) or not selected_repository_ids:
        return GraphRetrievalResult(
            (),
            {
                "enabled": bool(cfg.get("enabled", True)),
                "graph_fingerprint": graph_fingerprint,
                "seed_nodes": 0,
                "expanded_nodes": 0,
                "expanded_edges": 0,
                "cross_repo_edges": 0,
                "hops_used": 0,
                "repositories_reached": [],
                "budget": {
                    "allocated_context_chars": int(
                        cfg.get("max_context_chars", 3000)
                    ),
                    "used_context_chars": 0,
                },
            },
        )

    max_hops = max(0, int(cfg.get("max_hops", 2)))
    max_nodes = max(1, int(cfg.get("max_nodes", 24)))
    max_edges = max(0, int(cfg.get("max_edges", 40)))
    max_context_chars = max(0, int(cfg.get("max_context_chars", 3000)))
    min_confidence = float(cfg.get("min_edge_confidence", 0.8))

    nodes_by_id = {
        node.node_id: node
        for node in graph.nodes
        if node.repository_id in selected_repository_ids
    }
    eligible_edges = tuple(
        edge
        for edge in graph.edges
        if edge.confidence >= min_confidence
        and edge.source_repository_id in selected_repository_ids
        and edge.target_repository_id in selected_repository_ids
        and edge.source_node_id in nodes_by_id
        and edge.target_node_id in nodes_by_id
    )

    adjacency: dict[str, list[GraphEdge]] = {}
    for edge in eligible_edges:
        adjacency.setdefault(edge.source_node_id, []).append(edge)
        adjacency.setdefault(edge.target_node_id, []).append(edge)
    for values in adjacency.values():
        values.sort(
            key=lambda edge: (
                edge.edge_type,
                edge.source_node_id,
                edge.target_node_id,
                edge.edge_id,
            )
        )

    seeds = _seed_nodes(
        tuple(nodes_by_id.values()),
        selected_repository_ids,
        symbol=symbol,
        endpoint=endpoint,
        changed_files=changed_files,
        seed_items=seed_items,
    )
    seed_ids = {node.node_id for node in seeds}

    distance: dict[str, int] = {}
    path_edges: dict[str, tuple[str, ...]] = {}
    reach_confidence: dict[str, float] = {}
    cross_reached: dict[str, bool] = {}
    queue: deque[str] = deque()

    for seed in seeds[:max_nodes]:
        distance[seed.node_id] = 0
        path_edges[seed.node_id] = ()
        reach_confidence[seed.node_id] = 1.0
        cross_reached[seed.node_id] = False
        queue.append(seed.node_id)

    traversed_edges: dict[str, GraphEdge] = {}
    while queue and len(distance) < max_nodes:
        current_id = queue.popleft()
        current_distance = distance[current_id]
        if current_distance >= max_hops:
            continue
        current = nodes_by_id[current_id]
        for edge in adjacency.get(current_id, ()):
            if edge.edge_id not in traversed_edges:
                if len(traversed_edges) >= max_edges:
                    continue
                traversed_edges[edge.edge_id] = edge

            neighbor_id = (
                edge.target_node_id
                if edge.source_node_id == current_id
                else edge.source_node_id
            )
            if neighbor_id in distance:
                continue
            if len(distance) >= max_nodes:
                break

            neighbor = nodes_by_id[neighbor_id]
            distance[neighbor_id] = current_distance + 1
            path_edges[neighbor_id] = (
                *path_edges[current_id],
                edge.edge_id,
            )
            reach_confidence[neighbor_id] = edge.confidence
            cross_reached[neighbor_id] = (
                cross_reached[current_id]
                or current.repository_id != neighbor.repository_id
            )
            queue.append(neighbor_id)

    changed_set = {
        str(path).replace("\\", "/").lstrip("/")
        for path in changed_files
        if str(path).strip()
    }
    query_tokens = _tokens(query)
    ranked: list[tuple[float, int, GraphNode]] = []
    for node_id_value, node_distance in distance.items():
        node = nodes_by_id[node_id_value]
        changed = any(
            candidate in changed_set for candidate in _portable_candidates(node)
        )
        score = _score(
            node,
            query_tokens=query_tokens,
            distance=node_distance,
            seed=node_id_value in seed_ids,
            changed=changed,
            cross_repo=cross_reached.get(node_id_value, False),
            edge_confidence=reach_confidence.get(node_id_value, 1.0),
        )
        ranked.append((score, node_distance, node))

    ranked.sort(
        key=lambda row: (
            -row[0],
            row[1],
            row[2].repository_id,
            row[2].kind,
            row[2].path,
            row[2].node_id,
        )
    )

    repository_fingerprints = {
        node.repository_id: node.fingerprint
        for node in graph.nodes
        if node.kind == "repository"
        and node.repository_id in selected_repository_ids
    }
    items: list[ContextItem] = []
    used = 0
    for score, node_distance, node in ranked:
        if used >= max_context_chars:
            break
        edge_ids = list(path_edges.get(node.node_id, ()))
        payload = {
            "kind": node.kind,
            "label": node.label,
            "path": node.path,
            "symbol": node.symbol,
            "repository_path": node.repository_path,
            "edges": edge_ids,
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        text_value, cut = truncate(raw, max_context_chars - used)
        if not text_value:
            continue
        metadata: dict[str, Any] = {
            "repository_id": node.repository_id,
            "repository_path": node.repository_path,
            "repository_fingerprint": repository_fingerprints.get(
                node.repository_id, ""
            ),
            "graph_node_id": node.node_id,
            "graph_edge_ids": edge_ids,
            "graph_distance": node_distance,
            "graph_fingerprint": graph_fingerprint,
            "evidence_path": node.evidence,
            "kind": node.kind,
        }
        if cut:
            metadata["truncated"] = True
        provenance = dict(metadata)
        items.append(
            ContextItem(
                "workspace_graph",
                text_value,
                score,
                False,
                metadata,
                provenance,
            )
        )
        used += len(text_value)

    cross_repo_edges = sum(
        1
        for edge in traversed_edges.values()
        if edge.source_repository_id != edge.target_repository_id
    )
    repositories_reached = sorted(
        {
            nodes_by_id[node_id_value].repository_path
            for node_id_value in distance
        }
    )
    diagnostics: dict[str, Any] = {
        "enabled": True,
        "graph_fingerprint": graph_fingerprint,
        "seed_nodes": min(len(seeds), max_nodes),
        "expanded_nodes": len(distance),
        "expanded_edges": len(traversed_edges),
        "cross_repo_edges": cross_repo_edges,
        "hops_used": max(distance.values(), default=0),
        "repositories_reached": repositories_reached,
        "budget": {
            "allocated_context_chars": max_context_chars,
            "used_context_chars": used,
        },
    }
    return GraphRetrievalResult(tuple(items), diagnostics)
