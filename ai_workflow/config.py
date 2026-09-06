from __future__ import annotations
import json
from pathlib import Path
from typing import Any

DEFAULT_RELATIVE = Path("ai-workspace/config/control-plane.json")
REQUIRED_SECTIONS = ("budgets", "classifier", "context", "execution", "handoff", "memory", "models")


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _fraction(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


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
        _fraction(value, f"source share {name}")
    if sum(float(value) for value in shares.values()) > 1.000001:
        raise ValueError("source shares must sum to at most 1")

    for key in ("crg", "targeted_search", "semantic", "sufficiency", "adaptive_budget", "telemetry"):
        if not isinstance(data["context"].get(key), dict):
            raise ValueError(f"missing required section: context.{key}")
    semantic = data["context"]["semantic"]
    if semantic.get("mode", "auto") not in {"auto", "on", "off"}:
        raise ValueError("context.semantic.mode must be auto, on, or off")
    _positive_int(int(semantic.get("timeout_seconds", 0)), "context.semantic.timeout_seconds")
    _positive_int(int(semantic.get("max_results", 0)), "context.semantic.max_results")
    _fraction(data["context"]["sufficiency"].get("threshold"), "context.sufficiency.threshold")
    adaptive = data["context"]["adaptive_budget"]
    _fraction(adaptive.get("high_sufficiency_fraction"), "context.adaptive_budget.high_sufficiency_fraction")
    _fraction(adaptive.get("medium_sufficiency_fraction"), "context.adaptive_budget.medium_sufficiency_fraction")
    _positive_int(adaptive.get("minimum_chars"), "context.adaptive_budget.minimum_chars")
    if data["context"]["telemetry"].get("mode", "mutations") not in {"off", "mutations", "all"}:
        raise ValueError("context.telemetry.mode must be off, mutations, or all")
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
    return max(1, (len(text) + 3) // 4) if text else 0
