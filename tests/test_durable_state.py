from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


class DurableMemoryStoreTests(unittest.TestCase):
    @staticmethod
    def _record(id_: str = "mem-1") -> dict:
        return {
            "id": id_, "type": "decision",
            "created_at": "2026-01-01T00:00:00+00:00",
            "verified_at": "2026-01-01T00:00:00+00:00",
            "keywords": ["legacy"], "summary": "legacy decision",
            "evidence": "", "files": [], "source_hashes": {}, "confidence": 0.8,
        }

    def test_sqlite_store_imports_legacy_jsonl_once_backs_up_and_exports(self):
        from ai_workflow.memory_store import SQLiteMemoryStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy = root / "ai-workspace/memory/memory.jsonl"
            legacy.parent.mkdir(parents=True); legacy.write_text(json.dumps(self._record("mem-legacy")) + "\n", encoding="utf-8")
            store = SQLiteMemoryStore(root)
            self.assertEqual([row["id"] for row in store.list_records()], ["mem-legacy"])
            self.assertTrue(legacy.with_suffix(".jsonl.bak").exists())
            self.assertEqual(store.import_jsonl(legacy), 0)
            exported = root / "export.jsonl"; self.assertEqual(store.export_jsonl(exported), 1)
            self.assertEqual(json.loads(exported.read_text().strip())["id"], "mem-legacy")

    def test_replace_all_rolls_back_if_replacement_is_invalid(self):
        from ai_workflow.memory_store import SQLiteMemoryStore
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteMemoryStore(Path(td)); original = self._record("original"); store.insert(original)
            with self.assertRaises(sqlite3.IntegrityError):
                store.replace_all([self._record("dup"), self._record("dup")])
            self.assertEqual([row["id"] for row in store.list_records()], ["original"])

    def test_concurrent_insertions_are_transactional_and_connections_close(self):
        from ai_workflow.memory_store import SQLiteMemoryStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); errors: list[Exception] = []
            def write(index: int):
                try:
                    row = self._record(f"mem-{index}"); row["created_at"] = f"2026-01-01T00:00:{index:02d}+00:00"; row["verified_at"] = row["created_at"]
                    SQLiteMemoryStore(root).insert(row)
                except Exception as exc: errors.append(exc)
            threads = [threading.Thread(target=write, args=(i,)) for i in range(10)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(errors, []); self.assertEqual(len(SQLiteMemoryStore(root).list_records()), 10)

    def test_compatibility_memory_facade_uses_sqlite_and_preserves_staleness(self):
        from ai_workflow.memory import add_memory, search_memory
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / "a.py"; source.write_text("x=1", encoding="utf-8")
            add_memory(root, "verified-fix", "alpha bug", "fixed alpha", files=["a.py"])
            self.assertTrue((root / "ai-workspace/memory/memory.sqlite3").exists())
            self.assertFalse(search_memory(root, "alpha")[0]["stale"])
            source.write_text("x=2", encoding="utf-8"); self.assertTrue(search_memory(root, "alpha")[0]["stale"])


class TelemetryPrivacyTests(unittest.TestCase):
    def test_trace_redacts_task_by_default_and_keeps_fingerprint(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); rel = write_trace(root, RetrievalTrace("fix secret auth token", "small", "high", "exact"), {"context": {"telemetry": {"mode": "all"}}})
            payload = json.loads((root / rel).read_text(encoding="utf-8")); self.assertNotIn("task", payload); self.assertEqual(len(payload["task_fingerprint"]), 64)

    def test_task_text_requires_trusted_runtime_opt_in_and_is_redacted(self):
        from ai_workflow.telemetry import RetrievalTrace, STORE_TASK_TEXT_ENV, write_trace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = {"context": {"telemetry": {"store_task_text": True, "redact_patterns": [r"(?i)bearer\s+\S+", r"(?i)api[_-]?key\s*[=:]\s*\S+"]}}}
            with patch.dict(os.environ, {STORE_TASK_TEXT_ENV: "1"}, clear=True):
                rel = write_trace(root, RetrievalTrace("Bearer abc API_KEY=secret", "full", "high", "exact"), cfg)
            task = json.loads((root / rel).read_text(encoding="utf-8"))["task"]
            self.assertNotIn("abc", task); self.assertNotIn("secret", task); self.assertIn("[REDACTED]", task)

    def test_project_config_cannot_enable_task_text_when_config_is_omitted(self):
        from ai_workflow.config import DEFAULT_RELATIVE, default_config
        from ai_workflow.telemetry import RetrievalTrace, write_trace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = default_config(); cfg["context"]["telemetry"]["store_task_text"] = True
            path = root / DEFAULT_RELATIVE; path.parent.mkdir(parents=True); path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                rel = write_trace(root, RetrievalTrace("visible task", "small", "low", "exact"))
            self.assertNotIn("task", json.loads((root / rel).read_text()))

    def test_retention_limits_local_trace_files(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cfg = {"context": {"telemetry": {"max_trace_files": 2, "retention_days": 3650}}}
            for index in range(4): write_trace(root, RetrievalTrace(f"task {index}", "small", "low", "exact"), cfg)
            self.assertLessEqual(len(list((root / "ai-workspace/generated/traces").glob("*.json"))), 2)

    def test_summary_reports_latency_percentiles(self):
        from ai_workflow.telemetry import RetrievalTrace, summarize_traces, write_trace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for value in (10.0, 20.0, 30.0, 100.0):
                trace = RetrievalTrace("task", "small", "low", "exact", stage_latency_ms={"retrieval_total_ms": value, "semantic": value / 2})
                write_trace(root, trace, {})
            latency = summarize_traces(root)["latency_ms"]
            self.assertEqual(latency["retrieval_total_ms"]["p50"], 25.0)
            self.assertGreaterEqual(latency["retrieval_total_ms"]["p95"], 30.0)
            self.assertIn("semantic", latency)

    def test_repository_otlp_endpoint_cannot_trigger_export(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace
        cfg = {"context": {"telemetry": {"otlp_endpoint": "https://collector.invalid/v1/logs", "export_timeout_seconds": 0.1}}}
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.telemetry.urlopen", side_effect=OSError("offline")) as mocked_urlopen:
            root = Path(td); rel = write_trace(root, RetrievalTrace("task", "small", "low", "exact"), cfg); self.assertTrue((root / rel).exists())
            mocked_urlopen.assert_not_called()


if __name__ == "__main__": unittest.main()
