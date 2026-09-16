from __future__ import annotations

from pathlib import Path

from .path_policy import PathOutsideWorkspace, resolve_within_root
from .repository_registry import RepositorySpec, is_git_repository, load_registry


def _registry_roots(root: Path, config: dict) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for spec in load_registry(root, config):
        if not spec.included:
            continue
        try:
            resolved = root.resolve() if spec.relative_path == "." else resolve_within_root(root, spec.relative_path)
        except (PathOutsideWorkspace, OSError):
            continue
        if resolved in seen or not resolved.is_dir() or not is_git_repository(resolved):
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def active_repository_roots(root: Path, config: dict) -> list[Path]:
    """Return every active code repository without retrieval-root limits."""

    workspace = Path(root).resolve()
    registry_roots = _registry_roots(workspace, config)
    roots: list[Path] = []
    seen: set[Path] = set()

    if is_git_repository(workspace):
        roots.append(workspace)
        seen.add(workspace)

    for candidate in registry_roots:
        if candidate in seen:
            continue
        seen.add(candidate)
        roots.append(candidate)

    if roots:
        return roots

    # Backward compatibility for non-Git single-folder projects and tests.
    return [workspace]


def workspace_roots(root: Path, config: dict) -> list[Path]:
    """Return bounded retrieval roots for the active repository set.

    A non-Git control root is omitted when accepted nested Git repositories
    exist. Legacy workspace.roots remain an explicit compatibility escape hatch.
    """
    root = root.resolve()
    configured = ((config.get("workspace") or {}).get("roots") or [])
    roots = list(active_repository_roots(root, config))
    seen = set(roots)
    legacy = [Path(str(raw).strip()) for raw in configured if str(raw).strip()]
    for candidate in legacy:
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        roots.append(resolved)
    max_roots = int((config.get("workspace") or {}).get("max_roots", len(roots)))
    return roots[:max(1, max_roots)]


def registry_spec_to_root(root: Path, spec: RepositorySpec) -> Path:
    if spec.relative_path == ".":
        return root.resolve()
    return resolve_within_root(root, spec.relative_path)
