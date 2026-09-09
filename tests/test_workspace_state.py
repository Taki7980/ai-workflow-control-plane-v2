import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.workspace_state import workspace_fingerprint


class WorkspaceStateTests(unittest.TestCase):
    def _write_index_state(self, root: Path, generated_at: str, content: str = "same") -> None:
        generated = root / "ai-workspace" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        digest = __import__("hashlib").sha256(content.encode("utf-8")).hexdigest()
        (generated / "index-state.json").write_text(
            json.dumps({"version": 2, "generated_at": generated_at, "files": {"app.py": {"sha256": digest}}}),
            encoding="utf-8",
        )

    def test_fingerprint_ignores_checkout_path_and_generated_at(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "one"
            second = Path(td) / "two"
            first.mkdir()
            second.mkdir()
            self._write_index_state(first, "2026-01-01T00:00:00+00:00")
            self._write_index_state(second, "2026-09-01T00:00:00+00:00")

            first_snapshot = workspace_fingerprint(first)
            second_snapshot = workspace_fingerprint(second)

            self.assertNotEqual(first_snapshot["root"], second_snapshot["root"])
            self.assertEqual(first_snapshot["index_state_sha256"], second_snapshot["index_state_sha256"])
            self.assertEqual(first_snapshot["fingerprint"], second_snapshot["fingerprint"])

    def test_fingerprint_changes_when_index_content_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_index_state(root, "2026-01-01T00:00:00+00:00", "same")
            before = workspace_fingerprint(root)["fingerprint"]
            self._write_index_state(root, "2026-01-01T00:00:00+00:00", "different")
            after = workspace_fingerprint(root)["fingerprint"]
            self.assertNotEqual(before, after)

    def test_missing_changed_file_is_encoded_not_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            result = workspace_fingerprint(Path(td), ["missing.py"])
            self.assertEqual(result["changed_files"][0]["state"], "missing")


if __name__ == "__main__":
    unittest.main()
