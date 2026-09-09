from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol


class MemoryStore(Protocol):
    def insert(self, record: dict) -> None: ...
    def list_records(self) -> list[dict]: ...
    def replace_all(self, records: list[dict]) -> None: ...
    def import_jsonl(self, path: Path) -> int: ...
    def export_jsonl(self, path: Path) -> int: ...


class SQLiteMemoryStore:
    """Transactional durable memory store with idempotent JSONL migration."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "ai-workspace" / "memory" / "memory.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        legacy = self.root / "ai-workspace" / "memory" / "memory.jsonl"
        if legacy.exists():
            self.import_jsonl(legacy)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")

    @staticmethod
    def _payload(record: dict) -> tuple:
        return (
            str(record["id"]),
            str(record.get("type", "pattern")),
            str(record.get("created_at", "")),
            str(record.get("verified_at", record.get("created_at", ""))),
            float(record.get("confidence", 0.0)),
            json.dumps(record, ensure_ascii=False, sort_keys=True),
        )

    def insert(self, record: dict) -> None:
        payload = self._payload(record)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                payload,
            )

    def upsert(self, record: dict) -> None:
        payload = self._payload(record)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO memories(id,type,created_at,verified_at,confidence,record_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    created_at=excluded.created_at,
                    verified_at=excluded.verified_at,
                    confidence=excluded.confidence,
                    record_json=excluded.record_json
                """,
                payload,
            )

    def list_records(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json FROM memories ORDER BY created_at ASC, id ASC"
            ).fetchall()
        records: list[dict] = []
        for (raw,) in rows:
            try:
                record = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def replace_all(self, records: list[dict]) -> None:
        payloads = [self._payload(record) for record in records]
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM memories")
            conn.executemany(
                "INSERT INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                payloads,
            )

    def import_jsonl(self, path: Path) -> int:
        if not path.exists():
            return 0
        records: list[dict] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("id"):
                records.append(record)
        if not records:
            return 0
        inserted = 0
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for record in records:
                payload = self._payload(record)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                    payload,
                )
                inserted += max(0, int(cursor.rowcount))
        return inserted

    def export_jsonl(self, path: Path) -> int:
        records = self.list_records()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )
        return len(records)
