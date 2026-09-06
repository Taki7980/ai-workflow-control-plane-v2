import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.semantic import semantic_context, semantic_ready


class SemanticProviderTests(unittest.TestCase):
    def test_not_ready_without_command(self):
        self.assertFalse(semantic_ready({"context": {"semantic": {"command": ""}}}))

    def test_parses_json_candidates(self):
        cfg = {"context": {"semantic": {"command": "semantic-cmd", "timeout_seconds": 2}}}
        fake = type("P", (), {"returncode": 0, "stdout": json.dumps({"items": [{"text": "payment retry guard", "score": 0.91, "path": "payments.py"}]})})()
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.semantic.subprocess.run", return_value=fake):
            items = semantic_context(Path(td), "avoid duplicate charge", cfg, 5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "semantic")
        self.assertEqual(items[0].metadata["path"], "payments.py")
        self.assertEqual(items[0].metadata["retriever"], "semantic")

    def test_malformed_output_degrades_to_empty(self):
        cfg = {"context": {"semantic": {"command": "semantic-cmd", "timeout_seconds": 2}}}
        fake = type("P", (), {"returncode": 0, "stdout": "not-json"})()
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.semantic.subprocess.run", return_value=fake):
            self.assertEqual(semantic_context(Path(td), "query", cfg, 5), [])


if __name__ == "__main__":
    unittest.main()
