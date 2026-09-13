import json, tempfile, unittest, subprocess, shutil
from pathlib import Path
from ai_workflow.context_broker import detect_changed_files
from ai_workflow.repository_registry import discover_repositories, registry_payload

class GitDetectTests(unittest.TestCase):
    def test_non_git_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(detect_changed_files(root), [])

    def test_non_git_parent_detects_changes_in_active_child_repositories(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("admin-panel", "backend"):
                repo = root / name
                repo.mkdir()
                subprocess.run(
                    ["git", "init"],
                    cwd=repo,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
                file = repo / "file.py"
                file.write_text("a = 1\n", encoding="utf-8")
                subprocess.run(["git", "add", "file.py"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "commit", "-m", "init"],
                    cwd=repo,
                    stdout=subprocess.DEVNULL,
                    check=True,
                )

            payload = registry_payload(discover_repositories(root, max_depth=2))
            for row in payload["repositories"]:
                row["included"] = True
                row["reason"] = "auto-discovered"
            registry = root / "ai-workspace/config/repositories.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(payload), encoding="utf-8")

            (root / "admin-panel/file.py").write_text("a = 2\n", encoding="utf-8")
            (root / "backend/file.py").write_text("a = 3\n", encoding="utf-8")
            changed = detect_changed_files(root)

            self.assertIn("admin-panel/file.py", changed)
            self.assertIn("backend/file.py", changed)

    def test_git_repo_detects_modified_files(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            f = root / "file.py"
            f.write_text("a = 1\n")
            subprocess.run(["git", "add", "file.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, stdout=subprocess.DEVNULL, check=True)
            f.write_text("a = 2\n")
            changed = detect_changed_files(root)
            self.assertIn("file.py", changed)
