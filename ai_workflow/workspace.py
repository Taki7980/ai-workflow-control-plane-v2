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
    """Return every active repository without retrieval-root limits."""

    workspace = Path(root).resolve()
    registry_roots = _registry_roots(workspace, config)
    configured = ((config.get("workspace") or {}).get("roots") or [])
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

    # Legacy roots are explicit user configuration and remain supported,
    # including historical absolute paths outside the control workspace.
    for raw in configured:
        value = str(raw).strip()
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        roots.append(resolved)

    if roots:
        return roots

    # Backward compatibility for non-Git single-folder projects and tests.
    return [workspace]


def workspace_roots(root: Path, config: dict) -> list[Path]:
    """Return bounded retrieval roots for the active repository set."""

    roots = active_repository_roots(root, config)
    max_roots = int(
        (config.get("workspace") or {}).get(
            "max_roots",
            len(roots),
        )
    )
    return roots[:max(1, max_roots)]


def registry_spec_to_root(root: Path, spec: RepositorySpec) -> Path:
    if spec.relative_path == ".":
        return root.resolve()
    return resolve_within_root(root, spec.relative_path)
