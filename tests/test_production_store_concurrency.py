import multiprocessing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from queue import Empty
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.production_store import (
    append_production_event,
    open_production_store,
    production_store_path,
    production_store_status,
    reconcile_learning_store,
)


def _process_append_event(store_path: str, index: int, queue) -> None:
    import ai_workflow.production_store as production_store

    production_store.require_safe_sqlite_wal_runtime = lambda: {
        "safe_for_wal": True,
        "version": "test",
    }
    decision_id = f"{index:032x}"
    try:
        result = production_store.append_production_event(
            Path(store_path),
            "decision",
            {
                "decision_id": decision_id,
                "created_at": "2026-09-28T00:00:00+00:00",
                "worker": index,
            },
            event_id=f"decision:{decision_id}",
            busy_timeout_ms=15000,
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        queue.put(("error", type(exc).__name__, str(exc)))
    else:
        queue.put(("ok", bool(result["inserted"])))


def production_config():
    config = default_config()
    config["context"]["production"]["enabled"] = True
    config["context"]["production"]["sqlite_path"] = (
        "ai-workspace/generated/learning/production/concurrency.sqlite3"
    )
    return config


class ProductionStoreConcurrencyTests(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "ai_workflow.production_store.require_safe_sqlite_wal_runtime",
            return_value={"safe_for_wal": True, "version": "test"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_concurrent_process_writers_commit_without_corruption(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = production_store_path(root, config)
            with open_production_store(store):
                pass

            ctx = multiprocessing.get_context("spawn")
            queue = ctx.Queue()
            processes = [
                ctx.Process(
                    target=_process_append_event,
                    args=(str(store), index, queue),
                )
                for index in range(6)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
                self.assertFalse(process.is_alive())
                self.assertEqual(process.exitcode, 0)

            results = []
            for _ in processes:
                try:
                    results.append(queue.get(timeout=5))
                except Empty as exc:
                    self.fail(f"missing worker result: {exc}")

            self.assertTrue(all(row[0] == "ok" for row in results), results)
            self.assertTrue(all(row[1] is True for row in results))
            status = production_store_status(root, config)

        self.assertEqual(status["integrity_check"], "ok")
        self.assertEqual(status["journal_mode"], "wal")
        self.assertEqual(status["event_count"], len(processes))

    def test_reconcile_fails_closed_for_invalid_canonical_json(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = production_store_path(root, config)
            with open_production_store(store):
                pass
            invalid = (
                root
                / "ai-workspace"
                / "generated"
                / "learning"
                / "decisions"
                / "broken.json"
            )
            invalid.parent.mkdir(parents=True, exist_ok=True)
            invalid.write_text('{"decision_id":', encoding="utf-8")

            result = reconcile_learning_store(root, config)

        self.assertFalse(result["consistent"])
        self.assertEqual(len(result["invalid_canonical_files"]), 1)

    def test_reconcile_fails_closed_for_extra_mirror_event(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = production_store_path(root, config)
            decision_id = "a" * 32
            append_production_event(
                store,
                "decision",
                {
                    "decision_id": decision_id,
                    "created_at": "2026-09-28T00:00:00+00:00",
                },
                event_id=f"decision:{decision_id}",
            )

            result = reconcile_learning_store(root, config)

        self.assertFalse(result["consistent"])
        self.assertEqual(
            result["extra_in_store"],
            [f"decision:{decision_id}"],
        )

    def test_corrupt_sqlite_mirror_fails_closed(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = production_store_path(root, config)
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_bytes(b"not-a-sqlite-database")

            with self.assertRaises(sqlite3.DatabaseError):
                production_store_status(root, config)


if __name__ == "__main__":
    unittest.main()
