from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .io_utils import atomic_write_json, atomic_write_jsonl

GRAPH_SCHEMA_VERSION = 1
GRAPH_NODES_RELATIVE = Path("ai-workspace/generated/workspace-graph-nodes.jsonl")
GRAPH_EDGES_RELATIVE = Path("ai-workspace/generated/workspace-graph-edges.jsonl")
GRAPH_STATE_RELATIVE = Path("ai-workspace/generated/workspace-graph-state.json")


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    repository_id: str
    repository_path: str
    path: str
    symbol: str
    label: str
    fingerprint: str
    evidence: str


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    source_repository_id: str
    target_repository_id: str
    evidence_path: str
    evidence_line: int | None
    extractor: str
    confidence: float
    fingerprint: str


@dataclass(frozen=True)
class WorkspaceGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


def _portable_path(value: str) -> str:
    normalized = str(value).replace("\\", "/").strip()
    if normalized in {"", "."}:
        return normalized or "."
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("graph paths must be workspace-relative")
    return candidate.as_posix()


def _digest(parts: tuple[str, ...]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def node_id(
    kind: str,
    repository_id: str,
    portable_path: str,
    symbol_or_label: str,
    *,
    schema_version: int = GRAPH_SCHEMA_VERSION,
) -> str:
    return _digest(
        (
            str(schema_version),
            str(kind),
            str(repository_id),
            _portable_path(portable_path),
            str(symbol_or_label),
        )
    )


def edge_id(
    edge_type: str,
    source_node_id: str,
    target_node_id: str,
    evidence_key: str,
    *,
    schema_version: int = GRAPH_SCHEMA_VERSION,
) -> str:
    return _digest(
        (
            str(schema_version),
            str(edge_type),
            str(source_node_id),
            str(target_node_id),
            str(evidence_key).replace("\\", "/"),
        )
    )


def _node_sort_key(node: GraphNode) -> tuple[str, str, str, str, str]:
    return (
        node.repository_id,
        node.kind,
        node.path,
        node.symbol,
        node.node_id,
    )


def _edge_sort_key(edge: GraphEdge) -> tuple[str, str, str, str, str]:
    return (
        edge.source_node_id,
        edge.edge_type,
        edge.target_node_id,
        edge.evidence_path,
        edge.edge_id,
    )


def normalized_graph(graph: WorkspaceGraph) -> WorkspaceGraph:
    return WorkspaceGraph(
        nodes=tuple(sorted(graph.nodes, key=_node_sort_key)),
        edges=tuple(sorted(graph.edges, key=_edge_sort_key)),
    )


def graph_fingerprint(graph: WorkspaceGraph) -> str:
    graph = normalized_graph(graph)
    payload = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "nodes": [asdict(node) for node in graph.nodes],
        "edges": [asdict(edge) for edge in graph.edges],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_portable_graph(graph: WorkspaceGraph) -> None:
    for node in graph.nodes:
        _portable_path(node.repository_path)
        _portable_path(node.path)
        if node.evidence:
            _portable_path(node.evidence)
    for edge in graph.edges:
        if edge.evidence_path:
            _portable_path(edge.evidence_path)


def save_workspace_graph(
    root: Path,
    graph: WorkspaceGraph,
    state: dict[str, Any],
) -> None:
    root = Path(root).resolve()
    graph = normalized_graph(graph)
    _validate_portable_graph(graph)
    atomic_write_jsonl(
        root / GRAPH_NODES_RELATIVE,
        (asdict(node) for node in graph.nodes),
    )
    atomic_write_jsonl(
        root / GRAPH_EDGES_RELATIVE,
        (asdict(edge) for edge in graph.edges),
    )
    atomic_write_json(root / GRAPH_STATE_RELATIVE, dict(state), sort_keys=True)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("graph JSONL rows must be objects")
        rows.append(value)
    return rows


def load_workspace_graph(root: Path) -> tuple[WorkspaceGraph | None, dict[str, Any]]:
    root = Path(root).resolve()
    nodes_path = root / GRAPH_NODES_RELATIVE
    edges_path = root / GRAPH_EDGES_RELATIVE
    state_path = root / GRAPH_STATE_RELATIVE
    if not state_path.exists() or not nodes_path.exists() or not edges_path.exists():
        return None, {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return None, {}
        nodes = tuple(GraphNode(**row) for row in _load_jsonl(nodes_path))
        edges = tuple(GraphEdge(**row) for row in _load_jsonl(edges_path))
        graph = normalized_graph(WorkspaceGraph(nodes=nodes, edges=edges))
        _validate_portable_graph(graph)
        return graph, state
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, {}
