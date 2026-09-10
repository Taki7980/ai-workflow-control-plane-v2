from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .indexer import EXCLUDE, SOURCE_EXTS
from .workspace_graph import (
    GRAPH_STATE_RELATIVE,
    GraphEdge,
    GraphNode,
    WorkspaceGraph,
    edge_id,
    graph_fingerprint,
    load_workspace_graph,
    node_id,
    normalized_graph,
    save_workspace_graph,
)
from .workspace_selector import RepositoryCandidate, build_repository_candidates
from .workspace_state import aggregate_workspace_fingerprint

EXTRACTOR_VERSION = 1
_MAX_TEXT_FILE_BYTES = 500_000

_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)")
_JS_IMPORT = re.compile(
    r"(?:from\s+|require\(\s*)[\"']([^\"']+)[\"']"
)
_HTTP_LITERAL = re.compile(r"[\"'](/api/[A-Za-z0-9_./:{}-]+)[\"']")
_HTTP_METHOD = re.compile(r"\bmethod\s*:\s*[\"\']([A-Za-z]+)[\"\']", re.I)
_HTTP_VERB_CLIENT = re.compile(
    r"\b(?:axios|client|http|api|requests)\.(get|post|put|delete|patch)\s*\(",
    re.I,
)
_PYPROJECT_NAME = re.compile(r"^\s*name\s*=\s*[\"']([^\"']+)[\"']")
_PYPROJECT_DEP = re.compile(r"[\"']([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?(?:[<>=!~ ].*)?[\"']")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _safe_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTS:
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDE for part in rel.parts):
            continue
        yield path, rel.as_posix()


def _workspace_index_rows(workspace_root: Path, name: str) -> list[dict[str, Any]]:
    path = workspace_root / "ai-workspace/generated" / name
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _candidate_local_index_path(
    candidate: RepositoryCandidate,
    value: str,
    child_paths: tuple[str, ...],
) -> str | None:
    normalized = str(value).replace("\\", "/").lstrip("./")
    if not normalized:
        return None
    if candidate.repository_path == ".":
        if any(
            normalized.startswith(path.rstrip("/") + "/")
            for path in child_paths
        ):
            return None
        return normalized
    if candidate.repository_path.startswith("legacy:"):
        return None
    prefix = candidate.repository_path.rstrip("/") + "/"
    if not normalized.startswith(prefix):
        return None
    local = normalized[len(prefix) :]
    return local or None


def _manifest_package_info(root: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    found: list[tuple[str, str, tuple[str, ...]]] = []

    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            name = str(data.get("name", "")).strip()
            deps: set[str] = set()
            for key in ("dependencies", "devDependencies"):
                section = data.get(key)
                if isinstance(section, dict):
                    deps.update(
                        str(dep).strip()
                        for dep in section
                        if str(dep).strip()
                    )
            if name:
                found.append((name, "package.json", tuple(sorted(deps))))

    go_mod = root / "go.mod"
    if go_mod.exists():
        text = _safe_text(go_mod)
        module = ""
        deps: set[str] = set()
        in_require = False
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("module "):
                module = line.split(None, 1)[1].strip()
            elif line == "require (":
                in_require = True
            elif in_require and line == ")":
                in_require = False
            elif line.startswith("require ") and not in_require:
                parts = line.split()
                if len(parts) >= 2:
                    deps.add(parts[1])
            elif in_require and line and not line.startswith("//"):
                parts = line.split()
                if parts:
                    deps.add(parts[0])
        if module:
            found.append((module, "go.mod", tuple(sorted(deps))))

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = _safe_text(pyproject)
        in_project = False
        in_dependencies = False
        name = ""
        deps: set[str] = set()
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_project = line == "[project]"
                in_dependencies = False
                continue
            if not in_project:
                continue
            if not name:
                match = _PYPROJECT_NAME.match(line)
                if match:
                    name = match.group(1).strip()
            if line.startswith("dependencies") and "[" in line:
                in_dependencies = True
            if in_dependencies:
                for match in _PYPROJECT_DEP.finditer(line):
                    dep = match.group(1).strip()
                    if dep and dep != name:
                        deps.add(dep)
                if "]" in line:
                    in_dependencies = False
        requirements: set[str] = set()
        for req in sorted(root.glob("requirements*.txt")):
            for raw in _safe_text(req).splitlines():
                item = raw.split("#", 1)[0].strip()
                if not item or item.startswith(("-", ".")):
                    continue
                dep = re.split(r"[<>=!~;\[]", item, maxsplit=1)[0].strip()
                if dep:
                    requirements.add(dep)
        deps.update(requirements)
        if name:
            found.append((name, "pyproject.toml", tuple(sorted(deps))))

    return found


def _package_aliases(identity: str) -> set[str]:
    normalized = identity.strip()
    aliases = {normalized, normalized.replace("-", "_")}
    if "/" in normalized and not normalized.startswith("@"):
        aliases.add(normalized.rsplit("/", 1)[-1])
    return {alias for alias in aliases if alias}


def _extract_imports(path: Path, text: str) -> list[tuple[str, int]]:
    suffix = path.suffix.lower()
    found: list[tuple[str, int]] = []
    if suffix == ".py":
        for line_no, line in enumerate(text.splitlines(), 1):
            match = _PY_IMPORT.search(line)
            if match:
                found.append((match.group(1), line_no))
        return found

    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in _JS_IMPORT.finditer(line):
                found.append((match.group(1), line_no))
        return found

    if suffix == ".go":
        in_block = False
        for line_no, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if line == "import (":
                in_block = True
                continue
            if in_block and line == ")":
                in_block = False
                continue
            if line.startswith("import ") and not in_block:
                quoted = re.search(r"[\"']([^\"']+)[\"']", line)
                if quoted:
                    found.append((quoted.group(1), line_no))
            elif in_block:
                quoted = re.search(r"[\"']([^\"']+)[\"']", line)
                if quoted:
                    found.append((quoted.group(1), line_no))
    return found



def _extract_http_calls(text: str) -> list[tuple[str, str | None, int]]:
    found: list[tuple[str, str | None, int]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for match in _HTTP_LITERAL.finditer(line):
            prefix = line[: match.start()]
            is_fetch = "fetch(" in prefix.replace(" ", "")
            verb_match = _HTTP_VERB_CLIENT.search(prefix)
            if not is_fetch and verb_match is None:
                continue
            method_match = _HTTP_METHOD.search(line)
            method = (
                method_match.group(1).upper()
                if method_match
                else verb_match.group(1).upper()
                if verb_match
                else None
            )
            found.append((match.group(1), method, line_no))
    return found


def _matches_package(import_name: str, identity: str) -> bool:
    if import_name == identity or import_name.startswith(identity.rstrip("/") + "/"):
        return True
    first = import_name.split(".", 1)[0]
    return first in _package_aliases(identity)


def _node(
    *,
    kind: str,
    candidate: RepositoryCandidate,
    path: str,
    symbol: str = "",
    label: str = "",
    fingerprint: str = "",
    evidence: str = "",
) -> GraphNode:
    identity_label = symbol or label
    return GraphNode(
        node_id=node_id(kind, candidate.repository_id, path, identity_label),
        kind=kind,
        repository_id=candidate.repository_id,
        repository_path=candidate.repository_path,
        path=path,
        symbol=symbol,
        label=label or identity_label or path,
        fingerprint=fingerprint,
        evidence=evidence or path,
    )


def _edge(
    *,
    edge_type: str,
    source: GraphNode,
    target: GraphNode,
    evidence_path: str,
    evidence_line: int | None,
    extractor: str,
    confidence: float,
    evidence_key: str,
) -> GraphEdge:
    identifier = edge_id(
        edge_type,
        source.node_id,
        target.node_id,
        evidence_key,
    )
    return GraphEdge(
        edge_id=identifier,
        edge_type=edge_type,
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        source_repository_id=source.repository_id,
        target_repository_id=target.repository_id,
        evidence_path=evidence_path,
        evidence_line=evidence_line,
        extractor=extractor,
        confidence=confidence,
        fingerprint=identifier,
    )


def _current_identity(
    workspace_root: Path,
    config: dict,
) -> tuple[list[RepositoryCandidate], str, dict[str, str]]:
    candidates = build_repository_candidates(workspace_root, config, [])
    aggregate = aggregate_workspace_fingerprint(workspace_root, config)
    repository_fingerprints = {
        candidate.repository_id: candidate.fingerprint
        for candidate in sorted(candidates, key=lambda item: item.repository_id)
    }
    return candidates, str(aggregate.get("fingerprint", "")), repository_fingerprints


def graph_status(workspace_root: Path, config: dict) -> dict[str, Any]:
    workspace_root = Path(workspace_root).resolve()
    graph, state = load_workspace_graph(workspace_root)
    state_path = workspace_root / GRAPH_STATE_RELATIVE
    if graph is None:
        return {
            "status": "corrupt" if state_path.exists() else "missing",
            "reusable": False,
            "graph_fingerprint": "",
            "node_count": 0,
            "edge_count": 0,
        }

    _, aggregate_fingerprint, repository_fingerprints = _current_identity(
        workspace_root,
        config,
    )
    reusable = (
        int(state.get("schema_version", 0)) == 1
        and int(state.get("extractor_version", 0)) == EXTRACTOR_VERSION
        and state.get("aggregate_workspace_fingerprint")
        == aggregate_fingerprint
        and state.get("repository_fingerprints") == repository_fingerprints
    )
    return {
        "status": "ready" if reusable else "stale",
        "reusable": reusable,
        "graph_fingerprint": str(state.get("graph_fingerprint", "")),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
    }


def build_workspace_graph(
    workspace_root: Path,
    config: dict,
    *,
    force: bool = False,
) -> tuple[WorkspaceGraph, dict[str, Any]]:
    workspace_root = Path(workspace_root).resolve()
    candidates, aggregate_fingerprint, repository_fingerprints = _current_identity(
        workspace_root,
        config,
    )
    existing, existing_state = load_workspace_graph(workspace_root)
    if (
        not force
        and existing is not None
        and int(existing_state.get("schema_version", 0)) == 1
        and int(existing_state.get("extractor_version", 0)) == EXTRACTOR_VERSION
        and existing_state.get("aggregate_workspace_fingerprint")
        == aggregate_fingerprint
        and existing_state.get("repository_fingerprints")
        == repository_fingerprints
    ):
        reused_state = dict(existing_state)
        reused_state["reused"] = True
        return existing, reused_state

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    file_nodes: dict[tuple[str, str], GraphNode] = {}
    package_nodes: dict[str, list[GraphNode]] = {}
    package_dependencies: list[tuple[GraphNode, str, str]] = []
    file_text: dict[tuple[str, str], str] = {}
    candidate_by_id = {candidate.repository_id: candidate for candidate in candidates}

    for candidate in sorted(
        candidates,
        key=lambda item: (item.repository_id, item.repository_path.casefold()),
    ):
        repository_node = _node(
            kind="repository",
            candidate=candidate,
            path=".",
            label=candidate.repository_path,
            fingerprint=candidate.fingerprint,
            evidence=candidate.repository_path,
        )
        nodes[repository_node.node_id] = repository_node

        for source_path, rel in _iter_source_files(candidate.root):
            digest = _file_digest(source_path)
            file_node = _node(
                kind="file",
                candidate=candidate,
                path=rel,
                label=rel,
                fingerprint=digest,
                evidence=rel,
            )
            nodes[file_node.node_id] = file_node
            file_nodes[(candidate.repository_id, rel)] = file_node
            file_text[(candidate.repository_id, rel)] = _safe_text(source_path)
            contains = _edge(
                edge_type="CONTAINS",
                source=repository_node,
                target=file_node,
                evidence_path=rel,
                evidence_line=None,
                extractor="containment",
                confidence=1.0,
                evidence_key=rel,
            )
            edges[contains.edge_id] = contains

        for identity, manifest_path, dependencies in _manifest_package_info(
            candidate.root
        ):
            manifest_digest = _file_digest(candidate.root / manifest_path)
            package_node = _node(
                kind="package",
                candidate=candidate,
                path=manifest_path,
                symbol=identity,
                label=identity,
                fingerprint=manifest_digest,
                evidence=manifest_path,
            )
            nodes[package_node.node_id] = package_node
            package_nodes.setdefault(identity, []).append(package_node)
            contains = _edge(
                edge_type="CONTAINS",
                source=repository_node,
                target=package_node,
                evidence_path=manifest_path,
                evidence_line=None,
                extractor="manifest",
                confidence=1.0,
                evidence_key=f"{manifest_path}:{identity}",
            )
            edges[contains.edge_id] = contains
            for dependency in dependencies:
                package_dependencies.append(
                    (package_node, dependency, manifest_path)
                )

    child_paths = tuple(
        sorted(
            candidate.repository_path
            for candidate in candidates
            if candidate.repository_path != "."
            and not candidate.repository_path.startswith("legacy:")
        )
    )
    endpoint_nodes_by_route: dict[str, list[tuple[str, GraphNode]]] = {}
    for row in _workspace_index_rows(workspace_root, "endpoint-index.jsonl"):
        indexed_file = str(row.get("file", ""))
        route = str(row.get("path", "")).strip()
        method = str(row.get("method", "REQUEST")).upper()
        if not route:
            continue
        for candidate in candidates:
            local = _candidate_local_index_path(
                candidate,
                indexed_file,
                child_paths,
            )
            if not local:
                continue
            endpoint_node = _node(
                kind="endpoint",
                candidate=candidate,
                path=local,
                symbol=route,
                label=f"{method} {route}",
                fingerprint=str(row.get("sha256", "")) or candidate.fingerprint,
                evidence=local,
            )
            nodes[endpoint_node.node_id] = endpoint_node
            endpoint_nodes_by_route.setdefault(route, []).append((method, endpoint_node))
            source = file_nodes.get((candidate.repository_id, local))
            if source is not None:
                implements = _edge(
                    edge_type="IMPLEMENTS_ENDPOINT",
                    source=source,
                    target=endpoint_node,
                    evidence_path=local,
                    evidence_line=(
                        int(row["line"])
                        if isinstance(row.get("line"), int)
                        else None
                    ),
                    extractor="endpoint-index",
                    confidence=1.0,
                    evidence_key=f"{local}:{method}:{route}",
                )
                edges[implements.edge_id] = implements
            break

    all_package_nodes = [
        node
        for values in package_nodes.values()
        for node in values
    ]
    for source_package, dependency, manifest_path in package_dependencies:
        targets = package_nodes.get(dependency, [])
        if len(targets) != 1:
            continue
        target = targets[0]
        if target.repository_id == source_package.repository_id:
            continue
        relation = _edge(
            edge_type="DEPENDS_ON",
            source=source_package,
            target=target,
            evidence_path=manifest_path,
            evidence_line=None,
            extractor="manifest",
            confidence=1.0,
            evidence_key=f"{manifest_path}:{dependency}",
        )
        edges[relation.edge_id] = relation

    for (repository_id, rel), text in sorted(file_text.items()):
        source = file_nodes[(repository_id, rel)]
        candidate = candidate_by_id[repository_id]
        source_path = candidate.root / rel
        for imported, line_no in _extract_imports(source_path, text):
            matches = [
                target
                for target in all_package_nodes
                if target.repository_id != repository_id
                and _matches_package(imported, target.symbol)
            ]
            unique = {target.node_id: target for target in matches}
            if len(unique) != 1:
                continue
            target = next(iter(unique.values()))
            relation = _edge(
                edge_type="IMPORTS",
                source=source,
                target=target,
                evidence_path=rel,
                evidence_line=line_no,
                extractor="import",
                confidence=1.0,
                evidence_key=f"{rel}:{line_no}:{imported}",
            )
            edges[relation.edge_id] = relation

        for route, call_method, line_no in _extract_http_calls(text):
            targets = [
                (method, target)
                for method, target in endpoint_nodes_by_route.get(route, [])
                if not (
                    target.repository_id == repository_id
                    and target.path == rel
                )
            ]
            if call_method is not None:
                targets = [
                    (method, target)
                    for method, target in targets
                    if method == call_method
                ]
            if len(targets) != 1:
                continue
            target_method, target = targets[0]
            relation = _edge(
                edge_type="CALLS_API",
                source=source,
                target=target,
                evidence_path=rel,
                evidence_line=line_no,
                extractor="http-literal",
                confidence=0.9,
                evidence_key=(
                    f"{rel}:{line_no}:{call_method or target_method}:"
                    f"{route}:{target.node_id}"
                ),
            )
            edges[relation.edge_id] = relation

    files_by_repo_basename: dict[tuple[str, str], list[GraphNode]] = {}
    for (repository_id, _), node in file_nodes.items():
        files_by_repo_basename.setdefault(
            (repository_id, Path(node.path).name),
            [],
        ).append(node)

    for (repository_id, rel), test_node in sorted(file_nodes.items()):
        path = Path(rel)
        name = path.name
        target_names: list[str] = []
        if name.startswith("test_") and name.endswith(".py"):
            target_names.append(name[len("test_") :])
        if name.endswith("_test.go"):
            target_names.append(name[: -len("_test.go")] + ".go")
        for marker in (".test.", ".spec."):
            if marker in name:
                base, suffix = name.split(marker, 1)
                target_names.append(f"{base}.{suffix}")
        for target_name in target_names:
            matches = [
                node
                for node in files_by_repo_basename.get(
                    (repository_id, target_name),
                    [],
                )
                if node.node_id != test_node.node_id
            ]
            if len(matches) != 1:
                continue
            target = matches[0]
            relation = _edge(
                edge_type="TESTS",
                source=test_node,
                target=target,
                evidence_path=rel,
                evidence_line=None,
                extractor="test-naming",
                confidence=0.8,
                evidence_key=f"{rel}:{target.path}",
            )
            edges[relation.edge_id] = relation

    graph = normalized_graph(
        WorkspaceGraph(
            nodes=tuple(nodes.values()),
            edges=tuple(
                edge
                for edge in edges.values()
                if edge.confidence >= 0.8
            ),
        )
    )
    fingerprint = graph_fingerprint(graph)
    state: dict[str, Any] = {
        "schema_version": 1,
        "aggregate_workspace_fingerprint": aggregate_fingerprint,
        "repository_fingerprints": repository_fingerprints,
        "graph_fingerprint": fingerprint,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "extractor_version": EXTRACTOR_VERSION,
        "reused": False,
    }
    save_workspace_graph(workspace_root, graph, state)
    return graph, state
