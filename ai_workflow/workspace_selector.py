from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context_broker import detect_changed_files
from .math_retrieval import tokenize
from .repository_registry import is_git_repository, repository_id
from .workspace import workspace_roots
from .workspace_state import aggregate_workspace_fingerprint

_LOW_INFORMATION_QUERY_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "should",
        "the",
        "to",
        "we",
        "where",
        "whether",
        "with",
    }
)
_EXPLICIT_HINT_WEIGHT = 100.0
_CHANGED_FILE_WEIGHT = 40.0
_IDENTITY_WEIGHT = 12.0
_INDEX_WEIGHT = 3.0
_PRIMARY_PRIOR = 0.25


@dataclass(frozen=True)
class RepositoryCandidate:
    root: Path
    repository_id: str
    repository_path: str
    remote_identity: str | None
    fingerprint: str
    changed_files: tuple[str, ...]
    is_primary: bool


@dataclass(frozen=True)
class RepositorySelection:
    candidate: RepositoryCandidate
    score: float
    rank: int
    selected: bool
    reasons: tuple[str, ...]


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token for token in tokenize(text) if token not in _LOW_INFORMATION_QUERY_TOKENS
    }


def _fallback_repository_path(workspace_root: Path, repo_root: Path) -> str:
    if repo_root == workspace_root:
        return "."
    try:
        return repo_root.relative_to(workspace_root).as_posix()
    except ValueError:
        return f"legacy:{repo_root.name.casefold()}"


def _partition_explicit_changes(
    candidates: list[tuple[Path, str]],
    changed_files: list[str],
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {repo_path: [] for _, repo_path in candidates}
    child_paths = sorted(
        (
            repo_path
            for _, repo_path in candidates
            if repo_path != "." and not repo_path.startswith("legacy:")
        ),
        key=lambda value: (-len(value), value.casefold()),
    )
    has_primary = "." in out
    for raw in changed_files:
        value = str(raw).replace("\\", "/").strip("/")
        if not value:
            continue
        owner = None
        local = value
        for repo_path in child_paths:
            prefix = repo_path.rstrip("/") + "/"
            if value.startswith(prefix):
                owner = repo_path
                local = value[len(prefix) :]
                break
        if owner is None and has_primary:
            owner = "."
        if owner is not None and local:
            out[owner].append(local)
    return {key: sorted(set(values)) for key, values in out.items()}


def build_repository_candidates(
    workspace_root: Path,
    config: dict,
    explicit_changed_files: list[str] | None = None,
) -> list[RepositoryCandidate]:
    workspace_root = Path(workspace_root).resolve()
    roots = [Path(root).resolve() for root in workspace_roots(workspace_root, config)]
    git_roots = [root for root in roots if is_git_repository(root)]
    candidate_roots = git_roots or ([workspace_root] if workspace_root in roots else [])
    aggregate = aggregate_workspace_fingerprint(workspace_root, config)
    snapshots = {
        Path(str(item.get("root", ""))).resolve(): item
        for item in aggregate.get("repositories", [])
        if item.get("root")
    }
    identities: list[tuple[Path, str, dict[str, Any]]] = []
    for repo_root in candidate_roots:
        snapshot = snapshots.get(repo_root, {})
        repo_path = str(
            snapshot.get("relative_path")
            or _fallback_repository_path(workspace_root, repo_root)
        )
        identities.append((repo_root, repo_path, snapshot))

    if explicit_changed_files is None:
        change_map = {
            repo_path: sorted(set(detect_changed_files(repo_root)))
            for repo_root, repo_path, _ in identities
        }
    else:
        change_map = _partition_explicit_changes(
            [(repo_root, repo_path) for repo_root, repo_path, _ in identities],
            explicit_changed_files,
        )

    candidates: list[RepositoryCandidate] = []
    for repo_root, repo_path, snapshot in identities:
        remote = snapshot.get("remote_identity")
        repo_id = str(snapshot.get("repository_id") or repository_id(repo_path, remote))
        candidates.append(
            RepositoryCandidate(
                root=repo_root,
                repository_id=repo_id,
                repository_path=repo_path,
                remote_identity=str(remote) if remote else None,
                fingerprint=str(snapshot.get("fingerprint") or ""),
                changed_files=tuple(change_map.get(repo_path, [])),
                is_primary=repo_root == workspace_root and is_git_repository(repo_root),
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            not item.is_primary,
            item.repository_id,
            item.repository_path.casefold(),
        ),
    )


def _jsonl(path: Path) -> list[dict[str, Any]]:
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


def _candidate_rows(
    rows: list[dict[str, Any]],
    candidate: RepositoryCandidate,
    child_paths: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        file = str(row.get("file", "")).replace("\\", "/").lstrip("./")
        belongs = False
        if candidate.repository_path == ".":
            belongs = not any(
                file.startswith(path.rstrip("/") + "/") for path in child_paths
            )
        elif not candidate.repository_path.startswith("legacy:"):
            belongs = file.startswith(candidate.repository_path.rstrip("/") + "/")
        if belongs:
            out.append(row)
            if len(out) >= limit:
                break
    return out


def select_repositories(
    workspace_root: Path,
    candidates: list[RepositoryCandidate],
    query: str,
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
    max_selected: int = 3,
    max_index_candidates: int = 200,
) -> list[RepositorySelection]:
    if not candidates:
        return []
    workspace_root = Path(workspace_root).resolve()
    generated = workspace_root / "ai-workspace" / "generated"
    symbols = _jsonl(generated / "symbol-index.jsonl")
    endpoints = _jsonl(generated / "endpoint-index.jsonl")
    child_paths = tuple(
        sorted(
            candidate.repository_path
            for candidate in candidates
            if candidate.repository_path != "."
            and not candidate.repository_path.startswith("legacy:")
        )
    )
    query_tokens = _meaningful_tokens(query)
    scored: list[tuple[RepositoryCandidate, float, tuple[str, ...], bool]] = []
    for candidate in candidates:
        score = 0.0
        reasons: list[str] = []
        symbol_rows = _candidate_rows(
            symbols, candidate, child_paths, max_index_candidates
        )
        endpoint_rows = _candidate_rows(
            endpoints, candidate, child_paths, max_index_candidates
        )

        if symbol and any(
            str(row.get("symbol", "")).casefold() == symbol.casefold()
            for row in symbol_rows
        ):
            score += _EXPLICIT_HINT_WEIGHT
            reasons.append("symbol_hint")
        if endpoint and any(
            endpoint.casefold() in str(row.get("path", "")).casefold()
            for row in endpoint_rows
        ):
            score += _EXPLICIT_HINT_WEIGHT
            reasons.append("endpoint_hint")

        changed_tokens = _meaningful_tokens(" ".join(candidate.changed_files))
        if query_tokens & changed_tokens:
            score += _CHANGED_FILE_WEIGHT
            reasons.append("changed_file")

        identity_text = " ".join(
            filter(None, (candidate.repository_path, candidate.remote_identity or ""))
        )
        identity_overlap = len(query_tokens & _meaningful_tokens(identity_text))
        if identity_overlap:
            score += _IDENTITY_WEIGHT * identity_overlap
            reasons.append("identity_match")

        best_index_overlap = 0
        for row in [*symbol_rows, *endpoint_rows]:
            row_text = " ".join(
                str(row.get(key, "")) for key in ("symbol", "method", "path", "file")
            )
            best_index_overlap = max(
                best_index_overlap, len(query_tokens & _meaningful_tokens(row_text))
            )
        if best_index_overlap:
            score += _INDEX_WEIGHT * best_index_overlap
            reasons.append("index_match")

        has_evidence = bool(reasons)
        if candidate.is_primary:
            score += _PRIMARY_PRIOR
            reasons.append("primary_prior")
        scored.append((candidate, score, tuple(reasons), has_evidence))

    ordered = sorted(
        scored,
        key=lambda row: (
            -row[1],
            row[0].repository_id,
            row[0].repository_path.casefold(),
        ),
    )
    has_evidence = any(row[3] for row in ordered)
    selected_ids: set[str] = set()
    if len(ordered) == 1:
        selected_ids.add(ordered[0][0].repository_id)
    elif has_evidence:
        for candidate, score, reason_tuple, evidence in ordered:
            if evidence and score > 0 and len(selected_ids) < max(1, int(max_selected)):
                selected_ids.add(candidate.repository_id)
    else:
        primary = next((row for row in ordered if row[0].is_primary), None)
        if primary is not None:
            selected_ids.add(primary[0].repository_id)

    result: list[RepositorySelection] = []
    for rank, (candidate, score, reason_tuple, _) in enumerate(ordered, 1):
        selected = candidate.repository_id in selected_ids
        final_reasons = (
            reason_tuple if selected or reason_tuple else ("no_relevant_signal",)
        )
        result.append(
            RepositorySelection(candidate, score, rank, selected, final_reasons)
        )
    return result
