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

    def test_sqlite_store_never_auto_imports_repository_legacy_jsonl(self):
        from ai_workflow.memory_store import SQLiteMemoryStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy = root / "ai-workspace/memory/memory.jsonl"
            legacy.parent.mkdir(parents=True); legacy.write_text(json.dumps(self._record("mem-legacy")) + "\n", encoding="utf-8")
            store = SQLiteMemoryStore(root)
            self.assertEqual(store.list_records(), [])
            self.assertTrue(legacy.exists())
            self.assertFalse(legacy.with_suffix(".jsonl.bak").exists())

    def test_legacy_jsonl_import_requires_explicit_operator_action(self):
        from ai_workflow.memory_store import SQLiteMemoryStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); legacy = root / "legacy-memory.jsonl"
            legacy.write_text(json.dumps(self._record("mem-legacy")) + "\n", encoding="utf-8")
            store = SQLiteMemoryStore(root)
            self.assertEqual(store.import_jsonl(legacy), 1)
            self.assertEqual([row["id"] for row in store.list_records()], ["mem-legacy"])
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
    _TRUSTED_TELEMETRY_ENV = {
        "AI_WORKFLOW_OTLP_ENDPOINT",
        "AI_WORKFLOW_OTLP_ALLOWED_HOSTS",
        "AI_WORKFLOW_OTLP_HEADERS_JSON",
        "AI_WORKFLOW_OTLP_TIMEOUT_SECONDS",
        "AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT",
        "AI_WORKFLOW_TELEMETRY_HMAC_KEY",
    }

    def _clean_env(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in self._TRUSTED_TELEMETRY_ENV
        }

    def test_local_trace_omits_task_and_unkeyed_fingerprint_by_default(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            self._clean_env(),
            clear=True,
        ):
            root = Path(td)
            rel = write_trace(
                root,
                RetrievalTrace(
                    "fix secret auth token",
                    "small",
                    "high",
                    "exact",
                ),
                {"context": {"telemetry": {"mode": "all"}}},
            )
            payload = json.loads((root / rel).read_text(encoding="utf-8"))
            self.assertNotIn("task", payload)
            self.assertNotIn("task_fingerprint", payload)

    def test_remote_task_text_can_be_enabled_and_redacted_without_local_persistence(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        env = self._clean_env()
        env.update(
            {
                "AI_WORKFLOW_OTLP_ENDPOINT": "https://collector.example/v1/logs",
                "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": "collector.example",
                "AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT": "1",
            }
        )
        cfg = {
            "context": {
                "telemetry": {
                    "redact_patterns": [
                        r"(?i)bearer\s+\S+",
                        r"(?i)api[_-]?key\s*[=:]\s*\S+",
                    ]
                }
            }
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            env,
            clear=True,
        ), patch("ai_workflow.telemetry.OtlpHttpSink") as sink:
            root = Path(td)
            rel = write_trace(
                root,
                RetrievalTrace(
                    "Bearer abc API_KEY=secret",
                    "full",
                    "high",
                    "exact",
                ),
                cfg,
            )
            remote = sink.return_value.emit.call_args.args[0]
            self.assertNotIn("abc", remote["task"])
            self.assertNotIn("secret", remote["task"])
            self.assertIn("[REDACTED]", remote["task"])
            local = json.loads((root / rel).read_text(encoding="utf-8"))
            self.assertNotIn("task", local)

    def test_write_trace_loads_project_local_telemetry_config_when_config_is_omitted(self):
        from ai_workflow.config import DEFAULT_RELATIVE, default_config
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            self._clean_env(),
            clear=True,
        ):
            root = Path(td)
            cfg = default_config()
            cfg["context"]["telemetry"]["max_trace_files"] = 1
            cfg["context"]["telemetry"]["retention_days"] = 3650
            path = root / DEFAULT_RELATIVE
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(cfg), encoding="utf-8")

            write_trace(
                root,
                RetrievalTrace("first task", "small", "low", "exact"),
            )
            write_trace(
                root,
                RetrievalTrace("second task", "small", "low", "exact"),
            )
            traces = list(
                (root / "ai-workspace/generated/traces").glob("*.json")
            )
            self.assertEqual(len(traces), 1)

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

    def test_exporter_failure_never_breaks_local_trace(self):
        from ai_workflow.telemetry import RetrievalTrace, write_trace

        env = self._clean_env()
        env.update(
            {
                "AI_WORKFLOW_OTLP_ENDPOINT": "https://collector.example/v1/logs",
                "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": "collector.example",
            }
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            env,
            clear=True,
        ), patch(
            "ai_workflow.telemetry.OtlpHttpSink.emit",
            side_effect=OSError("offline"),
        ):
            root = Path(td)
            rel = write_trace(
                root,
                RetrievalTrace("task", "small", "low", "exact"),
                {"context": {"telemetry": {"mode": "all"}}},
            )
            self.assertTrue((root / rel).exists())


if __name__ == "__main__": unittest.main()
