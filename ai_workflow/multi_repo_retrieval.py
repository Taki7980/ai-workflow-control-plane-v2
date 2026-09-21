from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .repository_graph import RepositoryRelationship, load_repository_graph
from .workspace import registry_spec_to_root
from .repository_registry import load_registry, repository_id


_DEFAULT_RELATION_PRIORS = {
    RepositoryRelationship.DEPENDS_ON: 0.85,
    RepositoryRelationship.PUBLISHES_API: 0.80,
    RepositoryRelationship.CONSUMES_SCHEMA: 0.90,
    RepositoryRelationship.DEPLOYS: 0.70,
}


@dataclass(frozen=True)
class RoutedRepository:
    root: Path
    repository_id: str | None
    tier: str
    prior: float
    reason: str
    relationship: str | None = None
    anchor_repository_id: str | None = None


@dataclass(frozen=True)
class RepositoryRetrievalPlan:
    repositories: tuple[RoutedRepository, ...]
    graph_fingerprint: str
    primary_repository_ids: tuple[str, ...]
    expanded_repository_ids: tuple[str, ...]
    skipped_repository_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "strategy": "repository_first_graph_expansion",
            "graph_fingerprint": self.graph_fingerprint,
            "primary_repository_ids": list(self.primary_repository_ids),
            "expanded_repository_ids": list(self.expanded_repository_ids),
            "skipped_repository_ids": list(self.skipped_repository_ids),
            "repositories": [
                {
                    "repository_id": item.repository_id,
                    "tier": item.tier,
                    "prior": item.prior,
                    "reason": item.reason,
                    "relationship": item.relationship,
                    "anchor_repository_id": item.anchor_repository_id,
                }
                for item in self.repositories
            ],
        }


def _settings(config: dict) -> tuple[bool, int, int, set[RepositoryRelationship]]:
    raw = ((config.get("workspace") or {}).get("hierarchical_retrieval") or {})
    enabled = bool(raw.get("enabled", True))
    max_primary = max(1, int(raw.get("max_primary_repositories", 2)))
    max_expansions = max(0, int(raw.get("max_graph_expansions", 2)))
    requested = raw.get(
        "relationships",
        [kind.value for kind in RepositoryRelationship],
    )
    allowed: set[RepositoryRelationship] = set()
    for value in requested if isinstance(requested, list) else []:
        try:
            allowed.add(RepositoryRelationship(str(value)))
        except ValueError:
            continue
    return enabled, max_primary, max_expansions, allowed


def _registry_roots(control_root: Path, config: dict) -> dict[Path, tuple[str, str, str]]:
    mapped: dict[Path, tuple[str, str, str]] = {}
    for spec in load_registry(control_root, config):
        if not spec.included:
            continue
        try:
            root = registry_spec_to_root(control_root, spec).resolve()
        except (OSError, ValueError):
            continue
        mapped[root] = (
            repository_id(spec.relative_path, spec.remote_identity),
            spec.name,
            spec.relative_path,
        )
    return mapped


def _query_mentions(query: str, name: str, relative_path: str) -> bool:
    lowered = query.casefold()
    candidates = {
        name.casefold().strip(),
        relative_path.casefold().strip("./"),
    }
    for candidate in candidates:
        if not candidate or candidate == ".":
            continue
        if "/" in candidate or "\\" in candidate:
            if candidate in lowered:
                return True
            continue
        if re.search(rf"(?<![A-Za-z0-9_.-]){re.escape(candidate)}(?![A-Za-z0-9_.-])", lowered):
            return True
    return False


def _changed_matches(
    control_root: Path,
    repository_root: Path,
    relative_path: str,
    changed_files: list[str],
) -> bool:
    if not changed_files:
        return False
    if repository_root == control_root:
        nested_prefixes = []
        return any(
            not any(path.startswith(prefix) for prefix in nested_prefixes)
            for path in changed_files
        )
    prefix = relative_path.rstrip("/") + "/"
    return any(path == relative_path or path.startswith(prefix) for path in changed_files)


def plan_repository_retrieval(
    control_root: Path,
    roots: list[Path],
    query: str,
    changed_files: list[str],
    config: dict,
) -> RepositoryRetrievalPlan:
    """Select local repositories first, then bounded reviewed graph neighbors.

    Absence or invalidity of the reviewed repository graph never broadens the
    search. Graph expansion can only select roots already accepted by the
    workspace registry and already present in the caller's bounded root set.
    """

    workspace = Path(control_root).resolve()
    bounded_roots = [Path(root).resolve() for root in roots]
    enabled, max_primary, max_expansions, allowed = _settings(config)
    registry = _registry_roots(workspace, config)
    graph = load_repository_graph(workspace, config)
    graph_nodes = {node.repository_id for node in graph.nodes}

    identities: dict[Path, str | None] = {
        root: registry.get(root, (None, "", ""))[0]
        for root in bounded_roots
    }

    # Legacy workspace.roots may intentionally point at directories that have
    # no accepted registry identity. Preserve that historical explicit mode;
    # graph authority is only applied once the reviewed registry is in use.
    if bounded_roots and not any(identities.values()):
        hard_max = max(
            1,
            int((config.get("workspace") or {}).get("max_roots", len(bounded_roots))),
        )
        legacy = tuple(
            RoutedRepository(
                root,
                None,
                "legacy_explicit",
                1.0,
                "legacy_workspace_root",
            )
            for root in bounded_roots[:hard_max]
        )
        return RepositoryRetrievalPlan(legacy, graph.fingerprint, (), (), ())

    root_for_id = {
        repo_id: root
        for root, repo_id in identities.items()
        if repo_id is not None and repo_id in graph_nodes
    }

    signaled: list[tuple[Path, str]] = []
    for root in bounded_roots:
        repo_id, name, relative = registry.get(root, (None, root.name, "."))
        if repo_id and _changed_matches(workspace, root, relative, changed_files):
            signaled.append((root, "changed_files"))
        elif repo_id and _query_mentions(query, name, relative):
            signaled.append((root, "explicit_query_anchor"))

    if not signaled and bounded_roots:
        signaled = [(bounded_roots[0], "default_local_repository")]

    primary: list[RoutedRepository] = []
    seen_roots: set[Path] = set()
    for root, reason in signaled:
        if root in seen_roots or len(primary) >= max_primary:
            continue
        seen_roots.add(root)
        primary.append(
            RoutedRepository(root, identities.get(root), "primary", 1.0, reason)
        )

    if not enabled:
        skipped = tuple(
            repo_id
            for root, repo_id in identities.items()
            if repo_id and root not in seen_roots
        )
        return RepositoryRetrievalPlan(
            tuple(primary), graph.fingerprint,
            tuple(item.repository_id for item in primary if item.repository_id),
            (), skipped,
        )

    expanded: list[RoutedRepository] = []
    if max_expansions and allowed:
        primary_ids = {
            item.repository_id for item in primary if item.repository_id
        }
        candidates: list[tuple[float, str, Path, str, str]] = []
        for edge in graph.edges:
            if edge.relationship not in allowed:
                continue
            if edge.source_repository_id in primary_ids:
                neighbor = edge.target_repository_id
                anchor = edge.source_repository_id
                direction = "outgoing"
            elif edge.target_repository_id in primary_ids:
                neighbor = edge.source_repository_id
                anchor = edge.target_repository_id
                direction = "incoming"
            else:
                continue
            root = root_for_id.get(neighbor)
            if root is None or root in seen_roots:
                continue
            prior = _DEFAULT_RELATION_PRIORS[edge.relationship]
            candidates.append(
                (-prior, edge.edge_id, root, anchor, f"{edge.relationship.value}:{direction}")
            )

        for neg_prior, _edge_id, root, anchor, relation in sorted(candidates):
            if root in seen_roots or len(expanded) >= max_expansions:
                continue
            seen_roots.add(root)
            relationship = relation.split(":", 1)[0]
            expanded.append(
                RoutedRepository(
                    root,
                    identities.get(root),
                    "graph_expansion",
                    -neg_prior,
                    "reviewed_graph_neighbor",
                    relationship,
                    anchor,
                )
            )

    selected = [*primary, *expanded]
    hard_max = max(1, int((config.get("workspace") or {}).get("max_roots", len(selected) or 1)))
    selected = selected[:hard_max]
    selected_roots = {item.root for item in selected}
    skipped = tuple(
        repo_id
        for root, repo_id in identities.items()
        if repo_id and root not in selected_roots
    )
    return RepositoryRetrievalPlan(
        tuple(selected),
        graph.fingerprint,
        tuple(item.repository_id for item in selected if item.tier == "primary" and item.repository_id),
        tuple(item.repository_id for item in selected if item.tier == "graph_expansion" and item.repository_id),
        skipped,
    )
