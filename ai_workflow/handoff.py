from __future__ import annotations
import re
from pathlib import Path

REQUIRED = ["Lane / risk", "Goal / state", "Exact paths+symbols", "Context sources", "Ordered edits", "Invariants", "Changed files", "Checks", "Blockers", "Exact next step"]
HANDOFF_RELATIVE = Path("ai-workspace/handoff/HANDOFF.md")
LEGACY_HANDOFF_RELATIVE = Path(".ai/HANDOFF.md")

PLACEHOLDER_RE = re.compile(
    r"\[(?:answer\||small\||full\||low\||medium\||high\||goal and|bounded edit|cache/index|max \d+|contracts that|files changed|exact verification|one action|TODO|YOUR_)[^\]]*\]"
    r"|\{\{[^}]+\}\}"
    r"|<(?:insert|replace|TODO)[^>]*>",
    re.I,
)


def handoff_path(root: Path) -> Path:
    """Return the clean-layout handoff path inside ai-workspace."""

    return root / HANDOFF_RELATIVE


def _existing_handoff_path(root: Path) -> Path:
    clean = handoff_path(root)
    if clean.exists():
        return clean
    legacy = root / LEGACY_HANDOFF_RELATIVE
    if legacy.exists():
        return legacy
    return clean


def validate(root: Path, max_lines: int = 30) -> list[str]:
    path = _existing_handoff_path(root)
    if not path.exists():
        return [f"missing {HANDOFF_RELATIVE.as_posix()}"]
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    errors = []
    if len(lines) > max_lines:
        errors.append(f"handoff has {len(lines)} lines; cap is {max_lines}")
    for field in REQUIRED:
        if field.lower() not in text.lower():
            errors.append(f"missing field: {field}")
    if PLACEHOLDER_RE.search(text):
        errors.append("handoff still contains template placeholders")
    return errors


def render(decision, provider: str, context_sources: list[str], goal: str) -> str:
    sources = ", ".join(dict.fromkeys(context_sources)) or "none"
    return "\n".join([
        "# Handoff",
        f"- **Lane / risk**: {decision.lane.value} / {decision.risk.value}",
        f"- **Goal / state**: {goal.strip()} / routed",
        "- **Exact paths+symbols**: none yet",
        f"- **Context sources**: {sources}",
        f"- **Ordered edits**: execution provider = {provider}",
        "- **Invariants**: preserve existing contracts unless task explicitly changes them",
        "- **Changed files**: none",
        "- **Checks**: define focused checks before build",
        "- **Blockers**: none",
        "- **Exact next step**: inspect bounded context and finalize exact edit sites",
        "",
    ])
