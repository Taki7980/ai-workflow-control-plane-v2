from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol


class MemoryStore(Protocol):
    def insert(self, record: dict) -> None: ...
    def list_records(self) -> list[dict]: ...
    def replace_all(self, records: list[dict]) -> None: ...
    def import_jsonl(self, path: Path) -> int: ...
    def export_jsonl(self, path: Path) -> int: ...


class SQLiteMemoryStore:
    """Transactional durable memory store with reversible JSONL migration."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "ai-workspace" / "memory" / "memory.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        legacy = self.root / "ai-workspace" / "memory" / "memory.jsonl"
        if legacy.exists():
            self._migrate_legacy(legacy)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
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

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
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
        return records

    def _migrate_legacy(self, legacy: Path) -> None:
        backup = legacy.with_suffix(legacy.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(legacy, backup)
        expected_ids = {str(record["id"]) for record in self._read_jsonl(legacy)}
        self.import_jsonl(legacy)
        if expected_ids:
            actual_ids = {str(record.get("id")) for record in self.list_records()}
            missing = expected_ids - actual_ids
            if missing:
                raise RuntimeError("legacy memory migration validation failed: missing " + ", ".join(sorted(missing)))
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                ("legacy_jsonl_migrated", "1"),
            )

    def insert(self, record: dict) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                self._payload(record),
            )

    def upsert(self, record: dict) -> None:
        with self._connection() as conn:
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
                self._payload(record),
            )

    def list_records(self) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute("SELECT record_json FROM memories ORDER BY created_at ASC, id ASC").fetchall()
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
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM memories")
            conn.executemany(
                "INSERT INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                payloads,
            )

    def import_jsonl(self, path: Path) -> int:
        if not path.exists():
            return 0
        records = self._read_jsonl(path)
        if not records:
            return 0
        inserted = 0
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for record in records:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO memories(id,type,created_at,verified_at,confidence,record_json) VALUES(?,?,?,?,?,?)",
                    self._payload(record),
                )
                inserted += max(0, int(cursor.rowcount))
        return inserted

    def export_jsonl(self, path: Path) -> int:
        records = self.list_records()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return len(records)
