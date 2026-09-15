import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_workflow.code_review_graph import (
    repository_data_dir,
    sync_workspace_graphs,
    validate_graph_database,
)
from ai_workflow.context_broker import crg_context


@unittest.skipUnless(
    shutil.which("code-review-graph"),
    "code-review-graph is not installed",
)
class RealCodeReviewGraphIntegrationTests(unittest.TestCase):
    def _run_git(self, repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _fixture_repository(self, root: Path) -> Path:
        repo = root / "fixture"
        repo.mkdir()
        self._run_git(repo, "init")
        self._run_git(repo, "config", "user.email", "ci@example.invalid")
        self._run_git(repo, "config", "user.name", "AI Workflow CI")

        (repo / ".gitignore").write_text(
            "ai-workspace/code-review-graph/\n",
            encoding="utf-8",
        )
        (repo / "app.py").write_text(
            """
def helper(value: int) -> int:
    return value + 1


def handle(value: int) -> int:
    return helper(value)
""".lstrip(),
            encoding="utf-8",
        )
        (repo / "test_app.py").write_text(
            """
from app import handle


def test_handle() -> None:
    assert handle(1) == 2
""".lstrip(),
            encoding="utf-8",
        )

        self._run_git(repo, "add", ".")
        self._run_git(repo, "commit", "-m", "fixture")
        return repo

    def test_real_graph_build_is_valid_populated_and_manifested(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._fixture_repository(Path(td))
            result = sync_workspace_graphs(repo, {}, timeout=180)

            self.assertEqual(result["attempted"], 1, result)
            self.assertEqual(result["ready"], 1, result)
            self.assertTrue(result["repositories"][0]["ok"], result)

            data_dir = repository_data_dir(repo, repo)
            graph = data_dir / "graph.db"
            manifest_path = data_dir / "manifest.json"

            summary = validate_graph_database(graph)
            self.assertGreater(summary["node_count"], 0)
            self.assertGreater(summary["edge_count"], 0)

            connection = sqlite3.connect(graph)
            try:
                call_edges = connection.execute(
                    """
                    SELECT source_qualified, target_qualified
                    FROM edges
                    WHERE kind = 'CALLS'
                    """
                ).fetchall()
            finally:
                connection.close()

            self.assertTrue(
                any(
                    "handle" in str(source) and "helper" in str(target)
                    for source, target in call_edges
                ),
                call_edges,
            )

            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["manifest_schema"], 1)
            self.assertEqual(manifest["repository_relative_path"], ".")
            self.assertEqual(
                manifest["crg_schema_version"],
                summary["schema_version"],
            )
            self.assertEqual(manifest["node_count"], summary["node_count"])
            self.assertEqual(manifest["edge_count"], summary["edge_count"])
            self.assertEqual(manifest["generation_mode"], "build")
            self.assertEqual(manifest["graph_file"], "graph.db")
            self.assertRegex(manifest["graph_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(
                manifest["repository_fingerprint"],
                r"^[0-9a-f]{64}$",
            )


            structural = crg_context(
                repo,
                "Who calls helper?",
                "helper",
                None,
                5,
                patterns=("callers_of",),
            )
            self.assertEqual(len(structural), 1, structural)
            item = structural[0]
            self.assertEqual(item.source, "code_review_graph")
            self.assertEqual(item.metadata["pattern"], "callers_of")
            self.assertTrue(item.metadata["structural_valid"])
            self.assertGreaterEqual(item.metadata["result_count"], 1)

            normalized = json.loads(item.text)
            self.assertEqual(normalized["status"], "ok")
            self.assertEqual(normalized["pattern"], "callers_of")
            self.assertTrue(
                any(
                    "handle" in str(row.get("name", "")).lower()
                    or "handle" in str(
                        row.get("qualified_name", "")
                    ).lower()
                    for row in normalized.get("results", [])
                    if isinstance(row, dict)
                ),
                normalized,
            )


if __name__ == "__main__":
    unittest.main()
