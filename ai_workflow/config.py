from __future__ import annotations
import json
from pathlib import Path
from typing import Any

DEFAULT_RELATIVE = Path("ai-workspace/config/control-plane.json")
REQUIRED_SECTIONS = (
    "budgets",
    "classifier",
    "context",
    "execution",
    "handoff",
    "memory",
    "models",
)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_config(data: dict[str, Any]) -> None:
    if data.get("version") != 2:
        raise ValueError("unsupported control-plane config version")
    for section in REQUIRED_SECTIONS:
        if not isinstance(data.get(section), dict):
            raise ValueError(f"missing required section: {section}")

    for lane in ("answer", "small", "full"):
        budget = data["budgets"].get(lane)
        if not isinstance(budget, dict):
            raise ValueError(f"missing required budget: {lane}")
        _positive_int(budget.get("estimated_tokens"), f"budgets.{lane}.estimated_tokens")
        _positive_int(budget.get("output_tokens"), f"budgets.{lane}.output_tokens")

    shares = data["context"].get("source_shares")
    if not isinstance(shares, dict) or not shares:
        raise ValueError("context.source_shares must be a non-empty object")
    for name, value in shares.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError(f"source share {name} must be between 0 and 1")
    if sum(float(value) for value in shares.values()) > 1.000001:
        raise ValueError("source shares must sum to at most 1")

    for section, key in (("context", "crg"), ("context", "targeted_search")):
        if not isinstance(data[section].get(key), dict):
            raise ValueError(f"missing required section: {section}.{key}")
    _positive_int(data["handoff"].get("max_lines"), "handoff.max_lines")
    _positive_int(data["memory"].get("max_results"), "memory.max_results")


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
    validate_config(data)
    return data

def estimate_tokens(text: str) -> int:
    # Deliberately labeled estimate; provider tokenizers remain authoritative.
    return max(1, (len(text) + 3) // 4) if text else 0
