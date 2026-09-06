from __future__ import annotations

from pathlib import Path


def workspace_roots(root: Path, config: dict) -> list[Path]:
    """Return existing, unique repository roots with the primary root first."""
    configured = ((config.get("workspace") or {}).get("roots") or [])
    roots: list[Path] = [root.resolve()]
    seen = {roots[0]}
    for raw in configured:
        value = str(raw).strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate in seen or not candidate.is_dir():
            continue
        seen.add(candidate)
        roots.append(candidate)
    return roots
