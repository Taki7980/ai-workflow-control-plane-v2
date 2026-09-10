from __future__ import annotations

import json
from pathlib import Path

from .repository_registry import RepositorySpec


def _registry_roots(root: Path, config: dict) -> list[Path]:
    workspace = config.get("workspace") or {}
    registry = workspace.get("registry") or "ai-workspace/config/repositories.json"
    registry_path = Path(str(registry))
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    repositories = data.get("repositories", [])
    if not isinstance(repositories, list):
        return []
    roots: list[Path] = []
    for entry in repositories:
        if not isinstance(entry, dict) or not entry.get("included"):
            continue
        rel = str(entry.get("relative_path") or "").strip()
        if not rel:
            continue
        candidate = root if rel == "." else root / rel
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir():
            roots.append(resolved)
    return roots


def workspace_roots(root: Path, config: dict) -> list[Path]:
    """Return existing, unique repository roots with the primary root first.

    Legacy ``workspace.roots`` remain supported. The repository registry adds a
    safer multi-repo path: discovered repos are ignored until explicitly marked
    ``included: true`` in ``ai-workspace/config/repositories.json``.
    """
    configured = ((config.get("workspace") or {}).get("roots") or [])
    roots: list[Path] = [root.resolve()]
    seen = {roots[0]}
    for candidate in [*_registry_roots(root, config), *[Path(str(raw).strip()) for raw in configured if str(raw).strip()]]:
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
    return root if spec.relative_path == "." else root / spec.relative_path
