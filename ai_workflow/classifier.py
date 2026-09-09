from __future__ import annotations
import re
from .models import Lane, Risk, RouteDecision

CHANGE_WORDS = re.compile(r"\b(add|alter|build|create|change|edit|fix|implement|modify|patch|remove|rename|replace|rewrite|update|refactor|migrate|deploy)\b", re.I)
QUESTION_WORDS = re.compile(r"\b(what|why|how|where|which|who|whom|whose|when|explain|describe|compare|difference|understand|show|find|list|locate|tell)\b", re.I)
FILE_HINT = re.compile(r"(?:[\w./\\-]+\.(?:py|go|rs|js|ts|tsx|java|cs|cpp|h|rb|php|md|json|ya?ml))", re.I)

def _contains_any(text: str, items: list[str]) -> list[str]:
    lower = text.lower()
    matched = []
    for item in items:
        cleaned = item.lower().strip()
        if not cleaned:
            continue
        pattern = r"\b" + re.escape(cleaned) + r"\b"
        if re.search(pattern, lower):
            matched.append(item)
    return matched

def classify(task: str, config: dict) -> RouteDecision:
    text = " ".join(task.strip().split())
    lower = text.lower()
    c = config["classifier"]
    high = _contains_any(lower, c.get("high_risk_keywords", []))
    full = _contains_any(lower, c.get("full_keywords", []))
    answer = _contains_any(lower, c.get("answer_keywords", []))
    small = _contains_any(lower, c.get("small_keywords", []))
    structural = bool(_contains_any(lower, config["context"]["crg"].get("structural_keywords", [])))
    file_hints = FILE_HINT.findall(text)
    reasons: list[str] = []
    has_change = bool(CHANGE_WORDS.search(text))
    looks_question = bool(QUESTION_WORDS.search(text)) or text.endswith("?") or bool(answer)

    if looks_question and not has_change and not structural:
        reasons.append("read-only question/explanation")
        return RouteDecision(Lane.ANSWER, Risk.LOW, reasons, structural_context=False, confidence=0.96 if answer else 0.88)
    if high:
        reasons.append("high-risk change keyword: " + ", ".join(high[:3]))
        return RouteDecision(Lane.FULL, Risk.HIGH, reasons, structural_context=structural, confidence=0.99)
    if full or structural:
        if full:
            reasons.append("full-lane signal: " + ", ".join(full[:3]))
        if structural:
            reasons.append("multi-hop/structural context requested")
        return RouteDecision(Lane.FULL, Risk.MEDIUM, reasons, structural_context=structural, confidence=0.94 if structural else 0.9)
    if has_change:
        if 1 <= len(file_hints) <= 2 and (small or len(text.split()) <= 22):
            reasons.append("bounded low-complexity edit")
            reasons.append(f"explicit file scope: {len(file_hints)} file(s)")
            return RouteDecision(Lane.SMALL, Risk.LOW, reasons, structural_context=False, confidence=0.9 if small else 0.82)
        reasons.append("implementation scope not safely bounded")
        return RouteDecision(Lane.FULL, Risk.MEDIUM, reasons, structural_context=False, confidence=0.78)
    reasons.append("ambiguous task defaults to safe full-lane planning")
    return RouteDecision(Lane.FULL, Risk.MEDIUM, reasons, structural_context=False, confidence=0.62)
