from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.indexer import build_indexes, incremental_indexes, load_state


class IncrementalIndexFastPathTests(unittest.TestCase):
    def _root(self, td: str) -> tuple[Path, Path]:
        root = Path(td)
        (root / "ai-workspace" / "generated").mkdir(parents=True)
        source = root / "app.py"
        source.write_text("def hello():\n    return 1\n", encoding="utf-8")
        return root, source

    def test_full_index_records_size_and_mtime_ns(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._root(td)
            build_indexes(root)
            entry = load_state(root)["files"]["app.py"]
            stat = source.stat()
            self.assertEqual(entry["size"], stat.st_size)
            self.assertEqual(entry["mtime_ns"], stat.st_mtime_ns)
            self.assertTrue(entry["sha256"])

    def test_unchanged_stat_match_reuses_digest_without_hashing(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self._root(td)
            build_indexes(root)
            with patch("ai_workflow.indexer.sha256", side_effect=AssertionError("unchanged file must not be hashed")):
                stats = incremental_indexes(root)
            self.assertEqual(stats["changed"], 0)
            self.assertEqual(stats["stat_reused"], 1)
            self.assertEqual(stats["hashed"], 0)

    def test_changed_candidate_is_hashed_and_reparsed(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._root(td)
            build_indexes(root)
            source.write_text("def goodbye():\n    return 2\n", encoding="utf-8")
            stats = incremental_indexes(root)
            self.assertEqual(stats["changed"], 1)
            self.assertGreaterEqual(stats["hashed"], 1)
            symbols = [json.loads(line) for line in (root / "ai-workspace/generated/symbol-index.jsonl").read_text().splitlines()]
            self.assertEqual([row["symbol"] for row in symbols], ["goodbye"])

    def test_legacy_sha_only_state_hashes_once_and_upgrades_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root, _ = self._root(td)
            build_indexes(root)
            state_path = root / "ai-workspace/generated/index-state.json"
            state = json.loads(state_path.read_text())
            for entry in state["files"].values():
                entry.pop("size", None)
                entry.pop("mtime_ns", None)
            state_path.write_text(json.dumps(state), encoding="utf-8")

            stats = incremental_indexes(root)
            self.assertEqual(stats["changed"], 0)
            self.assertEqual(stats["hashed"], 1)
            upgraded = load_state(root)["files"]["app.py"]
            self.assertIn("size", upgraded)
            self.assertIn("mtime_ns", upgraded)

    def test_strict_hash_verifies_even_when_stat_metadata_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._root(td)
            build_indexes(root)
            old_state = load_state(root)["files"]["app.py"]
            old_stat = source.stat()
            original = source.read_text(encoding="utf-8")
            replacement = original.replace("1", "2")
            self.assertEqual(len(original.encode()), len(replacement.encode()))
            source.write_text(replacement, encoding="utf-8")
            os.utime(source, ns=(old_stat.st_atime_ns, old_state["mtime_ns"]))

            fast = incremental_indexes(root)
            self.assertEqual(fast["changed"], 0)
            strict = incremental_indexes(root, strict_hash=True)
            self.assertEqual(strict["changed"], 1)
            self.assertTrue(strict["strict_hash"])

    def test_removed_files_are_dropped_in_fast_and_strict_modes(self):
        for strict in (False, True):
            with self.subTest(strict=strict), tempfile.TemporaryDirectory() as td:
                root, source = self._root(td)
                build_indexes(root)
                source.unlink()
                stats = incremental_indexes(root, strict_hash=strict)
                self.assertEqual(stats["removed"], 1)
                self.assertEqual(load_state(root)["files"], {})


if __name__ == "__main__":
    unittest.main()
