import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_workflow.code_review_graph import (
    repository_data_dir,
    sync_workspace_graphs,
    workspace_health,
)
from ai_workflow.path_policy import PathOutsideWorkspace
from ai_workflow.repository_registry import RepositorySpec, registry_payload


class CodeReviewGraphWorkspaceTests(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        repo = root / "admin-panel"
        git_dir = repo / ".git"
        (git_dir / "refs/heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text(
            "ref: refs/heads/main\n",
            encoding="utf-8",
        )
        (git_dir / "refs/heads/main").write_text(
            "a" * 40 + "\n",
            encoding="utf-8",
        )
        registry = root / "ai-workspace/config/repositories.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                registry_payload(
                    [
                        RepositorySpec(
                            name="admin-panel",
                            relative_path="admin-panel",
                            included=True,
                            reason="auto-discovered",
                        )
                    ]
                )
            ),
            encoding="utf-8",
        )
        return repo

    def _write_valid_graph(self, data_dir: Path) -> Path:
        data_dir.mkdir(parents=True, exist_ok=True)
        graph = data_dir / "graph.db"
        connection = sqlite3.connect(graph)
        try:
            connection.executescript(
                """
                CREATE TABLE nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    qualified_name TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    line_start INTEGER,
                    line_end INTEGER,
                    language TEXT,
                    parent_name TEXT,
                    params TEXT,
                    return_type TEXT,
                    modifiers TEXT,
                    is_test INTEGER DEFAULT 0,
                    file_hash TEXT,
                    extra TEXT DEFAULT '{}',
                    community_id INTEGER,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    source_qualified TEXT NOT NULL,
                    target_qualified TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    line INTEGER DEFAULT 0,
                    extra TEXT DEFAULT '{}',
                    confidence REAL DEFAULT 1.0,
                    confidence_tier TEXT DEFAULT 'EXTRACTED',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", "10"),
            )
            connection.execute(
                """
                INSERT INTO nodes(
                    kind, name, qualified_name, file_path, line_start,
                    line_end, language, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Function",
                    "handle",
                    "app.py::handle",
                    "app.py",
                    1,
                    2,
                    "python",
                    1.0,
                ),
            )
            connection.execute(
                """
                INSERT INTO nodes(
                    kind, name, qualified_name, file_path, line_start,
                    line_end, language, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Function",
                    "helper",
                    "app.py::helper",
                    "app.py",
                    4,
                    5,
                    "python",
                    1.0,
                ),
            )
            connection.execute(
                """
                INSERT INTO edges(
                    kind, source_qualified, target_qualified, file_path,
                    line, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "CALLS",
                    "app.py::handle",
                    "app.py::helper",
                    "app.py",
                    2,
                    1.0,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return graph

    def test_repository_data_is_centralized_under_ai_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._workspace(root)
            data_dir = repository_data_dir(root, repo)
            self.assertEqual(
                data_dir,
                (root / "ai-workspace/code-review-graph/admin-panel").resolve(),
            )
            self.assertNotEqual(data_dir, repo / ".code-review-graph")

    @unittest.skipIf(os.name == "nt", "symlink creation may require elevated privileges")
    def test_repository_data_dir_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            data_root = root / "ai-workspace/code-review-graph"
            data_root.parent.mkdir(parents=True)
            data_root.symlink_to(outside, target_is_directory=True)

            with self.assertRaises(PathOutsideWorkspace):
                repository_data_dir(root, root)

    def test_setup_sync_builds_each_repo_with_central_crg_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._workspace(root)
            calls = []
            real_run = subprocess.run

            def fake_run(command, **kwargs):
                if command and command[0] == "git":
                    return real_run(command, **kwargs)
                calls.append((command, kwargs))
                if command[1:] == ["--version"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout="code-review-graph 2.3.8\n",
                        stderr="",
                    )
                data_dir = Path(kwargs["env"]["CRG_DATA_DIR"])
                self._write_valid_graph(data_dir)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch(
                "ai_workflow.code_review_graph.shutil.which",
                return_value="code-review-graph",
            ), patch(
                "ai_workflow.code_review_graph.subprocess.run",
                side_effect=fake_run,
            ):
                result = sync_workspace_graphs(root, {})

            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["ready"], 1)
            build_call = next(call for call in calls if call[0][1] == "build")
            command, kwargs = build_call
            self.assertEqual(command[1], "build")
            self.assertEqual(Path(kwargs["cwd"]).resolve(), repo.resolve())
            self.assertEqual(
                Path(kwargs["env"]["CRG_DATA_DIR"]).resolve(),
                (root / "ai-workspace/code-review-graph/admin-panel").resolve(),
            )
            manifest = (
                root
                / "ai-workspace/code-review-graph/admin-panel/manifest.json"
            )
            self.assertTrue(manifest.is_file())
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["manifest_schema"], 1)
            self.assertEqual(payload["repository_relative_path"], "admin-panel")
            self.assertEqual(payload["crg_schema_version"], 10)
            self.assertEqual(payload["node_count"], 2)
            self.assertEqual(payload["edge_count"], 1)
            self.assertEqual(payload["generation_mode"], "build")
            self.assertTrue(payload["graph_sha256"])
            self.assertFalse((repo / ".code-review-graph").exists())

    def test_sync_rejects_empty_graph_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._workspace(root)

            def fake_run(command, **kwargs):
                if command[1:] == ["--version"]:
                    return SimpleNamespace(
                        returncode=0,
                        stdout="code-review-graph 2.3.8\n",
                        stderr="",
                    )
                data_dir = Path(kwargs["env"]["CRG_DATA_DIR"])
                data_dir.mkdir(parents=True, exist_ok=True)
                (data_dir / "graph.db").touch()
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch(
                "ai_workflow.code_review_graph.shutil.which",
                return_value="code-review-graph",
            ), patch(
                "ai_workflow.code_review_graph.subprocess.run",
                side_effect=fake_run,
            ):
                result = sync_workspace_graphs(root, {})

            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["ready"], 0)
            self.assertFalse(result["repositories"][0]["ok"])
            self.assertIn("graph validation failed", result["repositories"][0]["error"])

    def test_health_checks_each_managed_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._workspace(root)
            data_dir = repository_data_dir(root, repo)
            self._write_valid_graph(data_dir)
            ok = SimpleNamespace(
                returncode=0,
                stdout='{"nodes": 42}',
                stderr="",
            )
            with patch(
                "ai_workflow.code_review_graph.shutil.which",
                return_value="code-review-graph",
            ), patch(
                "ai_workflow.code_review_graph.subprocess.run",
                return_value=ok,
            ):
                health = workspace_health(root, {})

            self.assertTrue(health["ready"])
            self.assertEqual(health["repository_count"], 1)
            self.assertEqual(health["ready_repositories"], 1)
            repository = health["repositories"][0]
            self.assertEqual(repository["validation"]["schema_version"], 10)
            self.assertEqual(repository["validation"]["node_count"], 2)
            self.assertEqual(repository["validation"]["edge_count"], 1)


if __name__ == "__main__":
    unittest.main()
