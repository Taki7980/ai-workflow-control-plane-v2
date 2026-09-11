from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .retrieval_learning import learning_root


STORE_SCHEMA_VERSION = "ai-workflow-production-store-v1"
DEFAULT_STORE_RELATIVE = (
    "ai-workspace/generated/learning/production/events.sqlite3"
)
EVENT_KINDS = frozenset(
    {
        "decision",
        "observation",
        "outcome",
        "deployment_state",
        "deployment_incident",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _production_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    context = config.get("context")
    if not isinstance(context, dict):
        return {}
    raw = context.get("production")
    return dict(raw) if isinstance(raw, dict) else {}


def production_store_enabled(config: dict[str, Any] | None) -> bool:
    return bool(_production_config(config).get("enabled", False))


def production_store_path(
    root: Path,
    config: dict[str, Any] | None,
) -> Path:
    cfg = _production_config(config)
    raw = str(cfg.get("sqlite_path", DEFAULT_STORE_RELATIVE)).strip()
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("context.production.sqlite_path must be relative")
    resolved = (root.resolve() / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(
            "context.production.sqlite_path must stay inside project root"
        )
    return resolved


def production_busy_timeout_ms(config: dict[str, Any] | None) -> int:
    cfg = _production_config(config)
    value = cfg.get("busy_timeout_ms", 5000)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return 5000
    return min(value, 60000)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            decision_id TEXT,
            policy_id TEXT,
            state_generation INTEGER,
            created_at TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS events_type_created_idx
        ON events(event_type, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS events_decision_idx
        ON events(decision_id)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS events_policy_generation_idx
        ON events(policy_id, state_generation)
        """
    )
    row = connection.execute(
        "SELECT value FROM metadata WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
            (STORE_SCHEMA_VERSION,),
        )
    elif str(row[0]) != STORE_SCHEMA_VERSION:
        raise ValueError(
            "production store schema mismatch: "
            f"expected {STORE_SCHEMA_VERSION}, found {row[0]}"
        )


@contextmanager
def open_production_store(
    path: Path,
    *,
    busy_timeout_ms: int = 5000,
) -> Iterator[sqlite3.Connection]:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_ms = min(max(1, int(busy_timeout_ms)), 60000)
    connection = sqlite3.connect(
        path,
        timeout=timeout_ms / 1000.0,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    try:
        mode_row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        mode = str(mode_row[0]).lower() if mode_row else ""
        if mode != "wal":
            raise RuntimeError(
                f"production store requires SQLite WAL mode; got {mode or 'unknown'}"
            )
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"PRAGMA busy_timeout={timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _ensure_schema(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        yield connection
    finally:
        connection.close()


def _event_identity(
    event_type: str,
    payload: dict[str, Any],
) -> tuple[str | None, str | None, int | None]:
    decision_id_raw = payload.get("decision_id")
    decision_id = (
        str(decision_id_raw).strip()
        if decision_id_raw is not None
        else None
    )
    deployment = payload.get("deployment")
    policy_id: str | None = None
    generation: int | None = None
    if isinstance(deployment, dict):
        raw_policy = deployment.get("policy_id")
        if raw_policy is not None:
            policy_id = str(raw_policy).strip() or None
        raw_generation = deployment.get("state_generation")
        if (
            not isinstance(raw_generation, bool)
            and isinstance(raw_generation, int)
        ):
            generation = raw_generation
    if event_type == "deployment_state":
        raw_policy = payload.get("policy_id")
        policy_id = str(raw_policy).strip() if raw_policy is not None else None
        raw_generation = payload.get("generation")
        if (
            not isinstance(raw_generation, bool)
            and isinstance(raw_generation, int)
        ):
            generation = raw_generation
    return decision_id, policy_id, generation


def append_production_event(
    path: Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    event_id: str | None = None,
    busy_timeout_ms: int = 5000,
) -> dict[str, Any]:
    kind = str(event_type).strip()
    if kind not in EVENT_KINDS:
        raise ValueError(f"unsupported production event type: {kind}")
    raw = _canonical(payload)
    digest = _sha256_text(raw)
    identity = str(event_id).strip() if event_id is not None else ""
    if not identity:
        identity = _sha256_text(f"{kind}:{digest}")
    decision_id, policy_id, generation = _event_identity(kind, payload)
    created_at = str(
        payload.get("created_at")
        or payload.get("observed_at")
        or payload.get("recorded_at")
        or payload.get("updated_at")
        or _utc_now()
    )
    with open_production_store(
        path,
        busy_timeout_ms=busy_timeout_ms,
    ) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing = connection.execute(
                "SELECT payload_sha256 FROM events WHERE event_id = ?",
                (identity,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != digest:
                    raise ValueError(
                        "production event id already exists with different payload"
                    )
                connection.commit()
                return {
                    "event_id": identity,
                    "inserted": False,
                    "payload_sha256": digest,
                }
            connection.execute(
                """
                INSERT INTO events(
                    event_id,
                    event_type,
                    decision_id,
                    policy_id,
                    state_generation,
                    created_at,
                    payload_sha256,
                    payload_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity,
                    kind,
                    decision_id,
                    policy_id,
                    generation,
                    created_at,
                    digest,
                    raw,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "event_id": identity,
        "inserted": True,
        "payload_sha256": digest,
    }


def mirror_learning_event(
    root: Path,
    config: dict[str, Any] | None,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not production_store_enabled(config):
        return {"enabled": False, "mirrored": False}
    decision_id = str(payload.get("decision_id", "")).strip()
    event_id = f"{event_type}:{decision_id}" if decision_id else None
    try:
        result = append_production_event(
            production_store_path(root, config),
            event_type,
            payload,
            event_id=event_id,
            busy_timeout_ms=production_busy_timeout_ms(config),
        )
        return {
            "enabled": True,
            "mirrored": True,
            **result,
        }
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        return {
            "enabled": True,
            "mirrored": False,
            "error": type(exc).__name__,
        }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def sync_learning_store(
    root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    if not production_store_enabled(config):
        raise ValueError("context.production.enabled must be true")
    base = learning_root(root)
    store = production_store_path(root, config)
    counters = {
        "scanned": 0,
        "inserted": 0,
        "already_present": 0,
        "invalid": 0,
    }
    for directory, event_type in (
        ("decisions", "decision"),
        ("observations", "observation"),
        ("outcomes", "outcome"),
    ):
        for path in sorted((base / directory).glob("*.json")):
            counters["scanned"] += 1
            payload = _load_json(path)
            if payload is None:
                counters["invalid"] += 1
                continue
            decision_id = str(payload.get("decision_id", "")).strip()
            if not decision_id:
                counters["invalid"] += 1
                continue
            result = append_production_event(
                store,
                event_type,
                payload,
                event_id=f"{event_type}:{decision_id}",
                busy_timeout_ms=production_busy_timeout_ms(config),
            )
            if result["inserted"]:
                counters["inserted"] += 1
            else:
                counters["already_present"] += 1
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "store": store.relative_to(root.resolve()).as_posix(),
        **counters,
    }


def production_store_status(
    root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    path = production_store_path(root, config)
    if not path.exists():
        return {
            "schema_version": STORE_SCHEMA_VERSION,
            "enabled": production_store_enabled(config),
            "exists": False,
            "store": path.relative_to(root.resolve()).as_posix(),
        }
    with open_production_store(
        path,
        busy_timeout_ms=production_busy_timeout_ms(config),
    ) as connection:
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        mode_row = connection.execute("PRAGMA journal_mode").fetchone()
        counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """
                SELECT event_type, COUNT(*)
                FROM events
                GROUP BY event_type
                ORDER BY event_type
                """
            ).fetchall()
        }
        total = sum(counts.values())
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "enabled": production_store_enabled(config),
        "exists": True,
        "store": path.relative_to(root.resolve()).as_posix(),
        "journal_mode": str(mode_row[0]).lower() if mode_row else None,
        "integrity_check": str(integrity_row[0]) if integrity_row else None,
        "event_count": total,
        "events_by_type": counts,
    }


def reconcile_learning_store(
    root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    path = production_store_path(root, config)
    if not path.exists():
        return {
            "consistent": False,
            "reason": "production_store_missing",
            "missing_in_store": [],
            "digest_mismatches": [],
        }
    expected: dict[str, str] = {}
    base = learning_root(root)
    for directory, event_type in (
        ("decisions", "decision"),
        ("observations", "observation"),
        ("outcomes", "outcome"),
    ):
        for file_path in sorted((base / directory).glob("*.json")):
            payload = _load_json(file_path)
            if payload is None:
                continue
            decision_id = str(payload.get("decision_id", "")).strip()
            if not decision_id:
                continue
            event_id = f"{event_type}:{decision_id}"
            expected[event_id] = _sha256_text(_canonical(payload))

    with open_production_store(
        path,
        busy_timeout_ms=production_busy_timeout_ms(config),
    ) as connection:
        actual = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                """
                SELECT event_id, payload_sha256
                FROM events
                WHERE event_type IN ('decision', 'observation', 'outcome')
                """
            ).fetchall()
        }
    missing = sorted(set(expected) - set(actual))
    mismatched = sorted(
        event_id
        for event_id in set(expected) & set(actual)
        if expected[event_id] != actual[event_id]
    )
    extra = sorted(set(actual) - set(expected))
    return {
        "consistent": not missing and not mismatched,
        "expected_events": len(expected),
        "stored_events": len(actual),
        "missing_in_store": missing,
        "digest_mismatches": mismatched,
        "extra_in_store": extra,
    }
