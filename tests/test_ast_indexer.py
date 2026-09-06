import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.indexer import build_indexes


class AstIndexerTests(unittest.TestCase):
    def test_python_ast_adds_kind_and_end_line(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ai-workspace/generated").mkdir(parents=True)
            (root / "sample.py").write_text("class PaymentService:\n    def charge(self):\n        return True\n", encoding="utf-8")
            stats = build_indexes(root)
            rows = [json.loads(line) for line in (root / "ai-workspace/generated/symbol-index.jsonl").read_text().splitlines()]
            by_name = {row["symbol"]: row for row in rows}
            self.assertGreaterEqual(stats["ast_files"], 1)
            self.assertEqual(by_name["PaymentService"]["parser"], "python-ast")
            self.assertEqual(by_name["PaymentService"]["kind"], "class")
            self.assertGreaterEqual(by_name["PaymentService"]["end_line"], by_name["PaymentService"]["line"])
            self.assertEqual(by_name["charge"]["kind"], "function")


if __name__ == "__main__":
    unittest.main()
