import tempfile, unittest, json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from ai_workflow.doctor import run
from ai_workflow.indexer import build_indexes

CFG = {
    "version": 2,
    "budgets": {"answer": {"estimated_tokens": 1200, "output_tokens": 450}, "small": {"estimated_tokens": 2500, "output_tokens": 700}, "full": {"estimated_tokens": 6000, "output_tokens": 1200}},
    "classifier": {},
    "context": {"crg": {"mode": "auto", "min_source_files": 250}},
    "execution": {"superpowers": {"mode": "auto"}},
    "handoff": {"max_lines": 30},
    "memory": {"max_results": 5, "minimum_confidence": 0.55}
}

class DoctorTests(unittest.TestCase):
    def test_failed_crg_status_is_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.py").write_text("def main(): pass\n")
            build_indexes(root)
            graph = root / ".code-review-graph" / "graph.db"
            graph.parent.mkdir()
            graph.touch()
            failed = SimpleNamespace(returncode=1, stdout="", stderr="broken graph")
            with patch("ai_workflow.doctor.shutil.which", return_value="code-review-graph"), patch(
                "ai_workflow.doctor.subprocess.run", return_value=failed
            ):
                result, _ = run(root, CFG)

            self.assertFalse(result["code_review_graph_health"]["ready"])

    def test_doctor_on_fresh_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.py").write_text("def main(): pass\n")
            build_indexes(root)
            result, ok = run(root, CFG)
            self.assertTrue(ok)
            self.assertEqual(result["handoff_errors"], [])
            self.assertEqual(result["index"]["tracked_files"], 1)
            self.assertEqual(result["index"]["stale_files"], 0)
