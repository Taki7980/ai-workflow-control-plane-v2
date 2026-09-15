import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.providers import detect, execution_provider, model_tier

ROOT = Path(__file__).parents[1]
CFG = json.loads((ROOT / "ai-workspace/config/control-plane.json").read_text())


class ProviderTests(unittest.TestCase):
    def _write_valid_graph(self, graph: Path) -> None:
        graph.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(graph)
        try:
            connection.executescript(
                """
                CREATE TABLE nodes (
                    id INTEGER PRIMARY KEY,
                    kind TEXT,
                    name TEXT,
                    qualified_name TEXT,
                    file_path TEXT
                );
                CREATE TABLE edges (
                    id INTEGER PRIMARY KEY,
                    kind TEXT,
                    source_qualified TEXT,
                    target_qualified TEXT,
                    file_path TEXT
                );
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO metadata(key, value)
                VALUES ('schema_version', '10');
                INSERT INTO nodes(
                    id, kind, name, qualified_name, file_path
                ) VALUES (
                    1, 'Function', 'handle', 'app.py::handle', 'app.py'
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def test_superpowers_can_be_forced_for_marketplace_installs(self):
        with patch.dict(os.environ, {"AI_WORKFLOW_SUPERPOWERS": "1"}):
            status = detect(ROOT, CFG)
            self.assertTrue(status.superpowers)
            self.assertEqual(
                execution_provider(Lane.FULL, CFG, status),
                "superpowers",
            )

    def test_crg_is_available_only_when_graph_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            graph = (
                root
                / "ai-workspace"
                / "code-review-graph"
                / "root"
                / "graph.db"
            )

            with patch(
                "ai_workflow.code_review_graph.shutil.which",
                return_value="code-review-graph",
            ):
                self.assertFalse(detect(root, CFG).code_review_graph)

                graph.parent.mkdir(parents=True)
                graph.touch()
                self.assertFalse(detect(root, CFG).code_review_graph)

                graph.unlink()
                self._write_valid_graph(graph)
                self.assertTrue(detect(root, CFG).code_review_graph)

    @unittest.skipIf(
        os.name == "nt",
        "symlink creation may require elevated privileges",
    )
    def test_crg_detection_fails_closed_on_storage_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / ".git").mkdir()

            data_root = root / "ai-workspace/code-review-graph"
            data_root.parent.mkdir(parents=True)
            data_root.symlink_to(outside, target_is_directory=True)

            with patch(
                "ai_workflow.code_review_graph.shutil.which",
                return_value="code-review-graph",
            ):
                self.assertFalse(detect(root, CFG).code_review_graph)

    def test_model_tier_scales_with_risk(self):
        low = RouteDecision(Lane.SMALL, Risk.LOW)
        high = RouteDecision(Lane.FULL, Risk.HIGH)
        self.assertEqual(model_tier(low, CFG), "fast")
        self.assertEqual(model_tier(high, CFG), "capable")


if __name__ == "__main__":
    unittest.main()
