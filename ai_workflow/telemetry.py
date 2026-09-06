from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RetrievalTrace:
    task: str
    lane: str
    risk: str
    intent: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    providers_attempted: list[str] = field(default_factory=list)
    providers_skipped: dict[str, str] = field(default_factory=dict)
    stage_latency_ms: dict[str, float] = field(default_factory=dict)
    candidates: dict[str, int] = field(default_factory=dict)
    selected: dict[str, int] = field(default_factory=dict)
    sufficiency: dict[str, Any] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)
    stale_rejections: int = 0
    budget_chars: int = 0
    used_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def trace_enabled(config: dict, lane: str, explicit: bool = False) -> bool:
    cfg = ((config.get("context") or {}).get("telemetry") or {})
    mode = str(cfg.get("mode", "mutations")).lower()
    if explicit:
        return True
    if mode == "off":
        return False
    if mode == "all":
        return True
    return lane != "answer"


def write_trace(root: Path, trace: RetrievalTrace) -> str:
    directory = root / "ai-workspace" / "generated" / "traces"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    filename = f"{stamp}-{os.getpid()}.json"
    target = directory / filename
    payload = json.dumps(trace.to_dict(), indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".trace-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp_name, target)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
    return target.relative_to(root).as_posix()


def _read_traces(root: Path, limit: int) -> list[dict[str, Any]]:
    directory = root / "ai-workspace" / "generated" / "traces"
    if not directory.exists():
        return []
    records = []
    for path in sorted(directory.glob("*.json"), reverse=True)[: max(1, limit)]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def summarize_traces(root: Path, limit: int = 200) -> dict[str, Any]:
    records = _read_traces(root, limit)
    by_intent: dict[str, int] = {}
    utilizations = []
    fallbacks = 0
    for record in records:
        intent = str(record.get("intent", "unknown"))
        by_intent[intent] = by_intent.get(intent, 0) + 1
        budget = int(record.get("budget_chars", 0) or 0)
        used = int(record.get("used_chars", 0) or 0)
        if budget:
            utilizations.append(used / budget)
        if record.get("fallbacks"):
            fallbacks += 1
    return {
        "runs": len(records),
        "by_intent": by_intent,
        "mean_budget_utilization": round(sum(utilizations) / len(utilizations), 4) if utilizations else 0.0,
        "fallback_rate": round(fallbacks / len(records), 4) if records else 0.0,
    }


def policy_recommendations(root: Path, limit: int = 200, minimum_runs: int = 20) -> dict[str, Any]:
    """Recommend reviewable policy changes from traces; never mutates config."""
    records = _read_traces(root, limit)
    recommendations: list[dict[str, Any]] = []
    if len(records) < minimum_runs:
        return {
            "runs": len(records),
            "minimum_runs": minimum_runs,
            "recommendations": [],
            "note": "insufficient observations; no policy recommendation produced",
        }

    by_intent: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_intent.setdefault(str(record.get("intent", "unknown")), []).append(record)

    for intent, rows in sorted(by_intent.items()):
        if len(rows) < max(5, minimum_runs // 5):
            continue
        fallback_rate = sum(bool(row.get("fallbacks")) for row in rows) / len(rows)
        suff_scores = [float((row.get("sufficiency") or {}).get("score", 0.0)) for row in rows]
        mean_suff = sum(suff_scores) / len(suff_scores)
        if fallback_rate >= 0.5:
            recommendations.append({
                "intent": intent,
                "signal": "high_fallback_rate",
                "observed": round(fallback_rate, 4),
                "action": "review provider availability, query-intent rules, or retrieval threshold before changing policy",
            })
        if mean_suff >= 0.9:
            recommendations.append({
                "intent": intent,
                "signal": "consistently_high_sufficiency",
                "observed": round(mean_suff, 4),
                "action": "benchmark a smaller soft context fraction; keep the hard lane ceiling unchanged",
            })
    return {
        "runs": len(records),
        "minimum_runs": minimum_runs,
        "recommendations": recommendations,
        "note": "recommendations are advisory only and never change deterministic safety routing",
    }
