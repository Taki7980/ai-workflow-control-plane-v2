from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


class DurableMemoryStoreTests(unittest.TestCase):
    def test_sqlite_store_imports_legacy_jsonl_once_and_exports(self):
        from ai_workflow.memory_store import SQLiteMemoryStore

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "ai-workspace/memory/memory.jsonl"
            legacy.parent.mkdir(parents=True)
            record = {
                "id": "mem-legacy",
                "type": "decision",
                "created_at": "2026-01-01T00:00:00+00:00",
                "verified_at": "2026-01-01T00:00:00+00:00",
                "keywords": ["legacy"],
                "summary": "legacy decision",
                "evidence": "",
                "files": [],
                "source_hashes": {},
                "confidence": 0.8,
            }
            legacy.write_text(json.dumps(record) + "\n", encoding="utf-8")
            store = SQLiteMemoryStore(root)
            self.assertEqual([row["id"] for row in store.list_records()], ["mem-legacy"])
            self.assertEqual(store.import_jsonl(legacy), 0)
            exported = root / "export.jsonl"
            store.export_jsonl(exported)
            self.assertEqual(json.loads(exported.read_text().strip())["id"], "mem-legacy")

    def test_concurrent_insertions_are_transactional(self):
        from ai_workflow.memory_store import SQLiteMemoryStore

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            errors: list[Exception] = []

            def write(index: int):
                try:
                    SQLiteMemoryStore(root).insert({
                        "id": f"mem-{index}", "type": "decision",
                        "created_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "verified_at": f"2026-01-01T00:00:{index:02d}+00:00",
                        "keywords": ["concurrent"], "summary": f"row {index}",
                        "evidence": "", "files": [], "source_hashes": {}, "confidence": 0.8,
                    })
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write, args=(index,)) for index in range(10)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(SQLiteMemoryStore(root).list_records()), 10)

    def test_compatibility_memory_facade_uses_sqlite_and_preserves_staleness(self):
        from ai_workflow.memory import add_memory, search_memory

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "a.py"
            source.write_text("x=1", encoding="utf-8")
            add_memory(root, "verified-fix", "alpha bug", "fixed alpha", files=["a.py"])
            self.assertTrue((root / "ai-workspace/memory/memory.sqlite3").exists())
            self.assertFalse(search_memory(root, "alpha")[0]["stale"])
            source.write_text("x=2", encoding="utf-8")
            self.assertTrue(search_memory(root, "alpha")[0]["stale"])


class TelemetryPrivacyTests(unittest.TestCase):
    def test_trace_redacts_task_by_default_and_keeps_fingerprint(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = RetrievalTrace("fix secret auth token", "small", "high", "exact")
            rel = write_trace(root, trace, {"context": {"telemetry": {"mode": "all"}}})
            payload = json.loads((root / rel).read_text(encoding="utf-8"))
            self.assertNotIn("task", payload)
            self.assertEqual(len(payload["task_fingerprint"]), 64)

    def test_task_text_can_be_explicitly_enabled(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = RetrievalTrace("diagnose payment retry", "full", "medium", "semantic")
            rel = write_trace(root, trace, {"context": {"telemetry": {"include_task_text": True}}})
            payload = json.loads((root / rel).read_text(encoding="utf-8"))
            self.assertEqual(payload["task"], "diagnose payment retry")

    def test_retention_limits_local_trace_files(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = {"context": {"telemetry": {"max_trace_files": 2, "retention_days": 3650}}}
            for index in range(4):
                write_trace(root, RetrievalTrace(f"task {index}", "small", "low", "exact"), cfg)
            files = list((root / "ai-workspace/generated/traces").glob("*.json"))
            self.assertLessEqual(len(files), 2)

    def test_exporter_failure_never_breaks_local_trace(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        cfg = {"context": {"telemetry": {"otlp_endpoint": "https://collector.invalid/v1/logs", "export_timeout_seconds": 0.1}}}
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.telemetry.urlopen", side_effect=OSError("offline")):
            root = Path(td)
            rel = write_trace(root, RetrievalTrace("task", "small", "low", "exact"), cfg)
            self.assertTrue((root / rel).exists())


if __name__ == "__main__":
    unittest.main()
