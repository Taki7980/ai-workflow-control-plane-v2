from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_workflow.repository_registry import discover_repositories, load_registry


class Stage2RegistryEdgeCaseTests(unittest.TestCase):
    def test_duplicate_repository_identity_invalidates_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "ai-workspace/config/repositories.json"
            path.parent.mkdir(parents=True)
            duplicate = {
                "name": "api",
                "relative_path": "api",
                "remote_identity": "github.com/acme/api",
                "included": True,
                "reason": "manual",
            }
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "repositories": [duplicate, {**duplicate, "included": False}],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_registry(root), [])

    def test_git_worktree_uses_common_remote_and_resolves_own_head(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/acme/repo.git"],
                cwd=repo,
                check=True,
            )
            (repo / "file.txt").write_text("ok\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            worktree = root / "repo-wt"
            subprocess.run(
                ["git", "worktree", "add", "-b", "worktree-test", str(worktree), "HEAD"],
                cwd=repo,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            expected_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            found = {
                item.relative_path: item
                for item in discover_repositories(root, max_depth=1)
            }
            spec = found["repo-wt"]
            self.assertEqual(spec.remote_identity, "github.com/acme/repo")
            self.assertEqual(spec.head_ref, "refs/heads/worktree-test")
            self.assertEqual(spec.head_sha, expected_head)


if __name__ == "__main__":
    unittest.main()
