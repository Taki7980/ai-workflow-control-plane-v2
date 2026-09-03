import tempfile, unittest, subprocess, shutil
from pathlib import Path
from ai_workflow.context_broker import detect_changed_files

class GitDetectTests(unittest.TestCase):
    def test_non_git_repo_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(detect_changed_files(root), [])

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
