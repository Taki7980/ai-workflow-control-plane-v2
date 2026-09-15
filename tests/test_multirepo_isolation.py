import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_workflow.bootstrap import setup
from ai_workflow.code_review_graph import repository_data_dir
from ai_workflow.config import load_config
from ai_workflow.doctor import run as doctor_run
from ai_workflow.workspace import workspace_roots


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class MultiRepositoryIsolationTests(unittest.TestCase):
    def _git_repo(
        self,
        parent: Path,
        name: str,
        source_name: str,
        source: str,
    ) -> Path:
        repo = parent / name
        repo.mkdir(parents=True)
        subprocess.run(
            ["git", "init"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "config", "user.email", "ci@example.invalid"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "AI Workflow CI"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                f"https://example.com/acme/{name}.git",
            ],
            cwd=repo,
            check=True,
        )
        (repo / source_name).write_text(source, encoding="utf-8")
        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "commit", "-m", "fixture"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return repo

    def _revenue_workspace(self, root: Path) -> tuple[Path, Path]:
        admin = self._git_repo(
            root,
            "admin-panel",
            "admin.py",
            "def admin_dashboard():\n    return 'admin'\n",
        )
        backend = self._git_repo(
            root,
            "backend",
            "service.py",
            "def revenue_service():\n    return 'backend'\n",
        )
        return admin, backend

    def test_non_git_control_root_is_not_a_retrieval_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin, backend = self._revenue_workspace(root)
            setup(
                root,
                "RevenueOS",
                index_mode="none",
                sync_crg=False,
            )
            config = load_config(root)

            roots = workspace_roots(root, config)

            self.assertEqual(
                roots,
                [admin.resolve(), backend.resolve()],
            )
            self.assertNotIn(root.resolve(), roots)

    def test_setup_builds_isolated_central_indexes_for_nested_repositories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin, backend = self._revenue_workspace(root)

            result = setup(
                root,
                "RevenueOS",
                index_mode="full",
                sync_crg=False,
            )

            self.assertEqual(
                result["repository_registry"]["accepted"],
                2,
            )
            self.assertEqual(result["index"]["repository_count"], 2)
            self.assertEqual(
                {
                    row["relative_path"]
                    for row in result["index"]["repositories"]
                },
                {"admin-panel", "backend"},
            )
            for name in ("admin-panel", "backend"):
                state = (
                    root
                    / "ai-workspace"
                    / "indexes"
                    / name
                    / "index-state.json"
                )
                self.assertTrue(state.is_file(), state)
            self.assertFalse(
                (
                    root
                    / "ai-workspace"
                    / "generated"
                    / "index-state.json"
                ).exists()
            )
            self.assertFalse((admin / "ai-workspace").exists())
            self.assertFalse((backend / "ai-workspace").exists())

    def test_parent_git_index_prunes_nested_repository_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "config", "user.email", "ci@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "AI Workflow CI"],
                cwd=root,
                check=True,
            )
            (root / "root.py").write_text(
                "def root_only():\n    return True\n",
                encoding="utf-8",
            )
            child = self._git_repo(
                root,
                "child",
                "child.py",
                "def child_only():\n    return True\n",
            )
            subprocess.run(
                ["git", "add", "root.py"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "commit", "-m", "root fixture"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            setup(
                root,
                "Nested",
                index_mode="full",
                sync_crg=False,
            )

            parent_state = json.loads(
                (
                    root
                    / "ai-workspace"
                    / "generated"
                    / "index-state.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                set(parent_state["files"]),
                {"root.py"},
            )
            child_state = (
                root
                / "ai-workspace"
                / "indexes"
                / "child"
                / "index-state.json"
            )
            self.assertTrue(child_state.is_file())
            self.assertFalse((child / "ai-workspace").exists())

    def test_doctor_reports_and_validates_each_active_repository_index(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin, backend = self._revenue_workspace(root)
            setup(
                root,
                "RevenueOS",
                index_mode="full",
                sync_crg=False,
            )
            config = load_config(root)

            healthy, healthy_ok = doctor_run(root, config)
            self.assertTrue(healthy_ok, healthy)
            self.assertEqual(
                {
                    row["relative_path"]
                    for row in healthy["repository_indexes"]
                },
                {"admin-panel", "backend"},
            )
            self.assertTrue(
                all(row["present"] for row in healthy["repository_indexes"])
            )

            (backend / "service.py").write_text(
                "def revenue_service():\n    return 'changed'\n",
                encoding="utf-8",
            )
            stale, stale_ok = doctor_run(root, config)

            self.assertFalse(stale_ok)
            by_path = {
                row["relative_path"]: row
                for row in stale["repository_indexes"]
            }
            self.assertEqual(by_path["admin-panel"]["stale_files"], 0)
            self.assertEqual(by_path["backend"]["stale_files"], 1)
            self.assertTrue(
                any(
                    "backend" in recommendation
                    for recommendation in stale["recommendations"]
                )
            )

    def test_crg_storage_remains_isolated_for_sibling_repositories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin, backend = self._revenue_workspace(root)

            admin_data = repository_data_dir(root, admin)
            backend_data = repository_data_dir(root, backend)

            self.assertNotEqual(admin_data, backend_data)
            self.assertEqual(
                admin_data,
                (
                    root
                    / "ai-workspace"
                    / "code-review-graph"
                    / "admin-panel"
                ).resolve(),
            )
            self.assertEqual(
                backend_data,
                (
                    root
                    / "ai-workspace"
                    / "code-review-graph"
                    / "backend"
                ).resolve(),
            )


if __name__ == "__main__":
    unittest.main()
