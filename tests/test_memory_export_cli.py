from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class MemoryExportCliTests(unittest.TestCase):
    def test_memory_export_writes_jsonl(self):
        from ai_workflow.cli import build_parser
        from ai_workflow.memory import add_memory

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            add_memory(root, "decision", "export", "keep portable")
            destination = root / "memory-export.jsonl"
            args = build_parser().parse_args([
                "--root", str(root), "memory", "export",
                "--format", "jsonl", "--output", str(destination),
            ])
            args.func(args)
            self.assertTrue(destination.exists())
            self.assertEqual(json.loads(destination.read_text().strip())["summary"], "keep portable")


if __name__ == "__main__":
    unittest.main()
