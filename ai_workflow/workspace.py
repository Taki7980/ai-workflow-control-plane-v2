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


def workspace_roots(root: Path, config: dict) -> list[Path]:
    """Return existing, unique repository roots with the primary root first.

    Registry roots are fail-closed and confined to ``root``. Legacy
    ``workspace.roots`` remain supported as an explicit compatibility escape
    hatch, including their historical support for absolute paths.
    """
    root = root.resolve()
    configured = ((config.get("workspace") or {}).get("roots") or [])
    roots: list[Path] = [root]
    seen = {root}
    legacy = [Path(str(raw).strip()) for raw in configured if str(raw).strip()]
    for candidate in [*_registry_roots(root, config), *legacy]:
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
