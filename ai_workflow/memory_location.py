from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


MEMORY_HOME_ENV = "AI_WORKFLOW_MEMORY_HOME"


def _default_memory_home() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return Path(base) / "ai-workflow" / "memory"
        return Path.home() / "AppData" / "Local" / "ai-workflow" / "memory"

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "ai-workflow"
            / "memory"
        )

    state = os.getenv("XDG_STATE_HOME", "").strip()
    base = Path(state).expanduser() if state else Path.home() / ".local" / "state"
    return base / "ai-workflow" / "memory"


def memory_home(root: Path) -> Path:
    """Return trusted durable-memory state root outside the repository."""

    repository = Path(root).expanduser().resolve()
    configured = os.getenv(MEMORY_HOME_ENV, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise ValueError(
                f"{MEMORY_HOME_ENV} memory home must be an absolute path"
            )
        base = candidate.resolve(strict=False)
    else:
        base = _default_memory_home().expanduser().resolve(strict=False)

    if base == repository or base.is_relative_to(repository):
        raise ValueError("memory home must stay outside the repository")
    return base


def workspace_memory_id(root: Path) -> str:
    repository = Path(root).expanduser().resolve()
    return hashlib.sha256(
        os.fsencode(str(repository))
    ).hexdigest()[:24]


def workspace_memory_dir(root: Path) -> Path:
    return memory_home(root) / workspace_memory_id(root)


def memory_db_path(root: Path) -> Path:
    return workspace_memory_dir(root) / "memory.sqlite3"
