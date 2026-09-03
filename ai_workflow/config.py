from __future__ import annotations
import json
from pathlib import Path
from typing import Any

DEFAULT_RELATIVE = Path("ai-workspace/config/control-plane.json")

def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "AGENTS.md").exists() and (candidate / "ai-workspace").exists():
            return candidate
    return current

def load_config(root: Path) -> dict[str, Any]:
    path = root / DEFAULT_RELATIVE
    if not path.exists():
        raise FileNotFoundError(f"control-plane config missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 2:
        raise ValueError("unsupported control-plane config version")
    return data

def estimate_tokens(text: str) -> int:
    # Deliberately labeled estimate; provider tokenizers remain authoritative.
    return max(1, (len(text) + 3) // 4) if text else 0
