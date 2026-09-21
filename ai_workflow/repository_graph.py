from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .path_policy import PathOutsideWorkspace, resolve_within_root
from .repository_registry import load_registry, repository_id


_GRAPH_VERSION = 1
_DEFAULT_GRAPH = Path("ai-workspace/config/repository-graph.json")


class RepositoryRelationship(str, Enum):
    """Code-owned cross-repository relationship vocabulary."""

    DEPENDS_ON = "depends_on"
    PUBLISHES_API = "publishes_api"
    CONSUMES_SCHEMA = "consumes_schema"
    DEPLOYS = "deploys"


@dataclass(frozen=True)
class RepositoryNode:
    repository_id: str
    name: str
    relative_path: str
    remote_identity: str | None


@dataclass(frozen=True)
class RepositoryEdge:
    source_repository_id: str
    target_repository_id: str
    relationship: RepositoryRelationship

    @property
    def edge_id(self) -> str:
        payload = {
            "source_repository_id": self.source_repository_id,
            "target_repository_id": self.target_repository_id,
            "relationship": self.relationship.value,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class WorkspaceRepositoryGraph:
    nodes: tuple[RepositoryNode, ...]
    edges: tuple[RepositoryEdge, ...]

    def node_ids(self) -> set[str]:
        return {node.repository_id for node in self.nodes}

    @property
    def fingerprint(self) -> str:
        payload = {
            "nodes": [node.repository_id for node in self.nodes],
            "edges": [edge.edge_id for edge in self.edges],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def outgoing(
        self,
        repository: str,
        relationships: Iterable[RepositoryRelationship] | None = None,
    ) -> tuple[RepositoryEdge, ...]:
        allowed = set(relationships) if relationships is not None else None
        return tuple(
            edge
            for edge in self.edges
            if edge.source_repository_id == repository
            and (allowed is None or edge.relationship in allowed)
        )

    def neighbors(
        self,
        repository: str,
        relationships: Iterable[RepositoryRelationship] | None = None,
    ) -> tuple[str, ...]:
        return tuple(
            edge.target_repository_id
            for edge in self.outgoing(repository, relationships)
        )


def graph_path(root: Path, config: dict | None = None) -> Path:
    workspace = ((config or {}).get("workspace") or {})
    configured = workspace.get("repository_graph") or _DEFAULT_GRAPH.as_posix()
    try:
        return resolve_within_root(Path(root), str(configured))
    except (PathOutsideWorkspace, OSError) as exc:
        raise ValueError("workspace.repository_graph must stay inside the project root") from exc


def _accepted_nodes(root: Path, config: dict | None) -> tuple[RepositoryNode, ...]:
    nodes: list[RepositoryNode] = []
    for spec in load_registry(root, config):
        if not spec.included:
            continue
        nodes.append(
            RepositoryNode(
                repository_id=repository_id(spec.relative_path, spec.remote_identity),
                name=spec.name,
                relative_path=spec.relative_path,
                remote_identity=spec.remote_identity,
            )
        )
    return tuple(sorted(nodes, key=lambda node: node.repository_id))


def _parse_edge(raw: object, accepted: set[str]) -> RepositoryEdge | None:
    if not isinstance(raw, dict):
        return None
    if set(raw) != {"source_repository_id", "target_repository_id", "relationship"}:
        return None
    source = raw.get("source_repository_id")
    target = raw.get("target_repository_id")
    relationship = raw.get("relationship")
    if not all(isinstance(value, str) and value.strip() for value in (source, target, relationship)):
        return None
    source = source.strip()
    target = target.strip()
    if source == target or source not in accepted or target not in accepted:
        return None
    try:
        kind = RepositoryRelationship(relationship.strip())
    except ValueError:
        return None
    return RepositoryEdge(source, target, kind)


def load_repository_graph(
    root: Path,
    config: dict | None = None,
) -> WorkspaceRepositoryGraph:
    """Load explicit cross-repository relationships, failing closed on ambiguity.

    Repository content never creates graph authority. Only accepted registry
    identities may participate, and malformed/unknown/duplicate edges invalidate
    the relationship set rather than being partially trusted.
    """

    nodes = _accepted_nodes(Path(root), config)
    accepted = {node.repository_id for node in nodes}
    path = graph_path(Path(root), config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return WorkspaceRepositoryGraph(nodes, ())

    if (
        not isinstance(data, dict)
        or data.get("version") != _GRAPH_VERSION
        or data.get("review_required") is not True
        or not isinstance(data.get("edges"), list)
    ):
        return WorkspaceRepositoryGraph(nodes, ())

    edges: list[RepositoryEdge] = []
    seen: set[tuple[str, str, RepositoryRelationship]] = set()
    for raw in data["edges"]:
        edge = _parse_edge(raw, accepted)
        if edge is None:
            return WorkspaceRepositoryGraph(nodes, ())
        key = (
            edge.source_repository_id,
            edge.target_repository_id,
            edge.relationship,
        )
        if key in seen:
            return WorkspaceRepositoryGraph(nodes, ())
        seen.add(key)
        edges.append(edge)

    return WorkspaceRepositoryGraph(
        nodes,
        tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.source_repository_id,
                    edge.target_repository_id,
                    edge.relationship.value,
                ),
            )
        ),
    )


def graph_summary(root: Path, config: dict | None = None) -> dict[str, Any]:
    graph = load_repository_graph(root, config)
    return {
        "version": _GRAPH_VERSION,
        "review_required": True,
        "path": str(graph_path(root, config)),
        "fingerprint": graph.fingerprint,
        "nodes": [
            {
                "repository_id": node.repository_id,
                "name": node.name,
                "relative_path": node.relative_path,
                "remote_identity": node.remote_identity,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "edge_id": edge.edge_id,
                "source_repository_id": edge.source_repository_id,
                "target_repository_id": edge.target_repository_id,
                "relationship": edge.relationship.value,
            }
            for edge in graph.edges
        ],
    }
