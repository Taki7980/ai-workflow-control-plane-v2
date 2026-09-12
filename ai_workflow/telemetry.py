from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


OTLP_ENDPOINT_ENV = "AI_WORKFLOW_OTLP_ENDPOINT"
OTLP_ALLOWED_HOSTS_ENV = "AI_WORKFLOW_OTLP_ALLOWED_HOSTS"
OTLP_HEADERS_JSON_ENV = "AI_WORKFLOW_OTLP_HEADERS_JSON"
OTLP_TIMEOUT_ENV = "AI_WORKFLOW_OTLP_TIMEOUT_SECONDS"
OTLP_INCLUDE_TASK_ENV = "AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT"
TELEMETRY_HMAC_KEY_ENV = "AI_WORKFLOW_TELEMETRY_HMAC_KEY"

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrustedOtlpSettings:
    endpoint: str
    timeout_seconds: float
    headers: dict[str, str]
    include_task_text: bool


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _trusted_headers() -> dict[str, str]:
    raw = os.getenv(OTLP_HEADERS_JSON_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in parsed.items()
        if str(key).strip()
    }


def _unsafe_destination(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(
        (
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_unspecified,
            address.is_reserved,
        )
    )


def _trusted_otlp_settings() -> TrustedOtlpSettings | None:
    endpoint = os.getenv(OTLP_ENDPOINT_ENV, "").strip()
    if not endpoint:
        return None

    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return None
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if _unsafe_destination(hostname):
        return None

    allowed_hosts = {
        host.strip().rstrip(".").lower()
        for host in os.getenv(OTLP_ALLOWED_HOSTS_ENV, "").split(",")
        if host.strip()
    }
    if hostname not in allowed_hosts:
        return None

    try:
        timeout_seconds = float(os.getenv(OTLP_TIMEOUT_ENV, "2.0"))
    except (TypeError, ValueError):
        timeout_seconds = 2.0
    timeout_seconds = min(10.0, max(0.05, timeout_seconds))

    return TrustedOtlpSettings(
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        headers=_trusted_headers(),
        include_task_text=_truthy_env(OTLP_INCLUDE_TASK_ENV),
    )


def _task_fingerprint(task: str) -> str | None:
    key = os.getenv(TELEMETRY_HMAC_KEY_ENV, "")
    if not key:
        return None
    return hmac.new(
        key.encode("utf-8"),
        task.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


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


class TelemetrySink(Protocol):
    def emit(self, payload: dict[str, Any]) -> None: ...


class LocalJsonSink:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = self.root / "ai-workspace" / "generated" / "traces"

    def emit(self, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        target = self.directory / f"{stamp}-{os.getpid()}.json"
        raw = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=".trace-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                try: os.unlink(temp_name)
                except OSError: pass
        payload["_local_path"] = target.relative_to(self.root).as_posix()


class OtlpHttpSink:
    """Best-effort OTLP-compatible JSON/HTTP log exporter with no runtime SDK dependency."""

    def __init__(self, endpoint: str, timeout_seconds: float = 2.0, headers: dict[str, str] | None = None):
        self.endpoint = endpoint.strip(); self.timeout_seconds = max(0.05, float(timeout_seconds)); self.headers = dict(headers or {})

    def emit(self, payload: dict[str, Any]) -> None:
        body = json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": [{"body": payload}]}]}]}, ensure_ascii=False).encode("utf-8")
        request = Request(  # noqa: S310 - endpoint validated by runtime-owned HTTPS host allowlist
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", **self.headers},
            method="POST",
        )
        opener = build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=self.timeout_seconds) as response:
            response.read(1)


def trace_enabled(config: dict, lane: str, explicit: bool = False) -> bool:
    cfg = ((config.get("context") or {}).get("telemetry") or {})
    mode = str(cfg.get("mode", "mutations")).lower()
    if explicit: return True
    if mode == "off": return False
    if mode == "all": return True
    return lane != "answer"


def _resolve_config(root: Path, config: dict | None) -> dict:
    if config is not None:
        return config
    try:
        from .config import load_config
        return load_config(root)
    except Exception:
        return {}


def _telemetry_config(config: dict | None) -> dict[str, Any]:
    return dict((((config or {}).get("context") or {}).get("telemetry") or {}))


def _redact(value: str, patterns: list[str]) -> str:
    out = value
    for pattern in patterns:
        try: out = re.sub(str(pattern), "[REDACTED]", out)
        except re.error: continue
    return out


def _redact_tree(value: Any, patterns: list[str]) -> Any:
    if isinstance(value, str): return _redact(value, patterns)
    if isinstance(value, list): return [_redact_tree(v, patterns) for v in value]
    if isinstance(value, dict): return {k: _redact_tree(v, patterns) for k, v in value.items()}
    return value


def _privacy_payload(
    trace: RetrievalTrace,
    config: dict | None,
    *,
    include_task_text: bool = False,
) -> dict[str, Any]:
    cfg = _telemetry_config(config)
    payload = trace.to_dict()
    task = str(payload.pop("task", ""))
    fingerprint = _task_fingerprint(task)
    if fingerprint:
        payload["task_fingerprint"] = fingerprint
    patterns = [str(x) for x in (cfg.get("redact_patterns") or []) if str(x)]
    if include_task_text:
        payload["task"] = _redact(task, patterns)
    return _redact_tree(payload, patterns)


def _prune_traces(root: Path, config: dict | None) -> None:
    cfg = _telemetry_config(config); directory = root / "ai-workspace" / "generated" / "traces"
    if not directory.exists(): return
    try: retention_days = max(0, int(cfg.get("retention_days", 30)))
    except (TypeError, ValueError): retention_days = 30
    try: max_files = max(1, int(cfg.get("max_trace_files", 200)))
    except (TypeError, ValueError): max_files = 200
    files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if retention_days > 0:
        cutoff = time.time() - retention_days * 86400
        for path in list(files):
            try:
                if path.stat().st_mtime < cutoff: path.unlink(); files.remove(path)
            except OSError: pass
    for path in files[max_files:]:
        try: path.unlink()
        except OSError: pass


def write_trace(
    root: Path,
    trace: RetrievalTrace,
    config: dict | None = None,
) -> str:
    resolved = _resolve_config(root, config)

    local_payload = _privacy_payload(
        trace,
        resolved,
        include_task_text=False,
    )
    local = LocalJsonSink(root)
    local.emit(local_payload)
    _prune_traces(root, resolved)

    trusted = _trusted_otlp_settings()
    if trusted is not None:
        export_payload = _privacy_payload(
            trace,
            resolved,
            include_task_text=trusted.include_task_text,
        )
        try:
            OtlpHttpSink(
                trusted.endpoint,
                timeout_seconds=trusted.timeout_seconds,
                headers=trusted.headers,
            ).emit(export_payload)
        except Exception as exc:  # noqa: BLE001 - export is best-effort
            _LOGGER.warning("OTLP export failed: %s", type(exc).__name__)

    return str(local_payload["_local_path"])


def _read_traces(root: Path, limit: int) -> list[dict[str, Any]]:
    directory = root / "ai-workspace" / "generated" / "traces"
    if not directory.exists(): return []
    records = []
    for path in sorted(directory.glob("*.json"), reverse=True)[: max(1, limit)]:
        try: record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): continue
        if isinstance(record, dict): records.append(record)
    return records


def _percentile(values: list[float], q: float) -> float | None:
    if not values: return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1: return round(ordered[0], 2)
    pos = (len(ordered) - 1) * q; lo = int(pos); hi = min(lo + 1, len(ordered) - 1); frac = pos - lo
    return round(ordered[lo] * (1 - frac) + ordered[hi] * frac, 2)


def _latency_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    stages: dict[str, list[float]] = {}
    for record in records:
        for name, raw in (record.get("stage_latency_ms") or {}).items():
            try: stages.setdefault(str(name), []).append(float(raw))
            except (TypeError, ValueError): continue
    return {name: {"p50": _percentile(values, .50), "p95": _percentile(values, .95), "p99": _percentile(values, .99), "mean": round(statistics.mean(values), 2)} for name, values in sorted(stages.items())}


def summarize_traces(root: Path, limit: int = 200) -> dict[str, Any]:
    records = _read_traces(root, limit); by_intent: dict[str, int] = {}; utilizations = []; fallbacks = 0
    for record in records:
        intent = str(record.get("intent", "unknown")); by_intent[intent] = by_intent.get(intent, 0) + 1
        budget = int(record.get("budget_chars", 0) or 0); used = int(record.get("used_chars", 0) or 0)
        if budget: utilizations.append(used / budget)
        if record.get("fallbacks"): fallbacks += 1
    return {"runs": len(records), "by_intent": by_intent,
            "mean_budget_utilization": round(sum(utilizations) / len(utilizations), 4) if utilizations else 0.0,
            "fallback_rate": round(fallbacks / len(records), 4) if records else 0.0,
            "latency_ms": _latency_summary(records)}


def policy_recommendations(root: Path, limit: int = 200, minimum_runs: int = 20) -> dict[str, Any]:
    records = _read_traces(root, limit); recommendations: list[dict[str, Any]] = []
    if len(records) < minimum_runs:
        return {"runs": len(records), "minimum_runs": minimum_runs, "recommendations": [], "note": "insufficient observations; no policy recommendation produced"}
    by_intent: dict[str, list[dict[str, Any]]] = {}
    for record in records: by_intent.setdefault(str(record.get("intent", "unknown")), []).append(record)
    for intent, rows in sorted(by_intent.items()):
        if len(rows) < max(5, minimum_runs // 5): continue
        fallback_rate = sum(bool(row.get("fallbacks")) for row in rows) / len(rows)
        suff_scores = [float((row.get("sufficiency") or {}).get("score", 0.0)) for row in rows]; mean_suff = sum(suff_scores) / len(suff_scores)
        if fallback_rate >= 0.5: recommendations.append({"intent": intent, "signal": "high_fallback_rate", "observed": round(fallback_rate, 4), "action": "review provider availability, query-intent rules, or retrieval threshold before changing policy"})
        if mean_suff >= 0.9: recommendations.append({"intent": intent, "signal": "consistently_high_sufficiency", "observed": round(mean_suff, 4), "action": "benchmark a smaller soft context fraction; keep the hard lane ceiling unchanged"})
    return {"runs": len(records), "minimum_runs": minimum_runs, "recommendations": recommendations, "note": "recommendations are advisory only and never change deterministic safety routing"}
