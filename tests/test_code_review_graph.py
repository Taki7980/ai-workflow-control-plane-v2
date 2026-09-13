import json
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

    def test_setup_sync_builds_each_repo_with_central_crg_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._workspace(root)
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
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
            self.assertEqual(result["ready"], 1)
            command, kwargs = calls[0]
            self.assertEqual(command[1], "build")
            self.assertEqual(Path(kwargs["cwd"]).resolve(), repo.resolve())
            self.assertEqual(
                Path(kwargs["env"]["CRG_DATA_DIR"]).resolve(),
                (root / "ai-workspace/code-review-graph/admin-panel").resolve(),
            )
            self.assertFalse((repo / ".code-review-graph").exists())

    def test_health_checks_each_managed_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._workspace(root)
            data_dir = repository_data_dir(root, repo)
            data_dir.mkdir(parents=True)
            (data_dir / "graph.db").touch()
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


if __name__ == "__main__":
    unittest.main()
