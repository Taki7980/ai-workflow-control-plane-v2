from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_workflow.repository_registry import (
    discover_repositories,
    load_registry,
    registry_payload,
    remote_identity,
    workspace_registry_fingerprint,
)
from ai_workflow.workspace import workspace_roots


class RepositoryRegistryTests(unittest.TestCase):
    def _git_repo(self, parent: Path, name: str, remote: str) -> Path:
        repo = parent / name
        repo.mkdir()
        git_dir = repo / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / "main").write_text("a" * 40 + "\n", encoding="utf-8")
        (git_dir / "config").write_text(
            f'[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = {remote}\n',
            encoding="utf-8",
        )
        return repo

    def test_remote_identity_removes_credentials_and_normalizes_git_urls(self):
        self.assertEqual(
            remote_identity("https://token@example.com/Taki7980/Repo.git"),
            "example.com/taki7980/repo",
        )
        self.assertEqual(
            remote_identity("git@github.com:Taki7980/Repo.git"),
            "github.com/taki7980/repo",
        )
        self.assertTrue(str(remote_identity("file:///private/repo")).startswith("opaque:"))

    def test_discovery_finds_sibling_repos_without_accepting_them(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git_repo(root, "frontend", "https://github.com/acme/frontend.git")
            self._git_repo(root, "backend", "git@github.com:acme/backend.git")

            found = discover_repositories(root, max_depth=2)
            paths = [repo.relative_path for repo in found]
            self.assertEqual(paths, ["backend", "frontend"])
            self.assertFalse(any(repo.included for repo in found))
            payload = registry_payload(found)
            self.assertTrue(payload["review_required"])
            self.assertEqual(len(payload["repositories"]), 2)
            self.assertNotIn(str(root), workspace_registry_fingerprint(found))

    def test_workspace_roots_uses_only_accepted_registry_entries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend = self._git_repo(root, "frontend", "https://github.com/acme/frontend.git")
            backend = self._git_repo(root, "backend", "https://github.com/acme/backend.git")
            registry = root / "ai-workspace/config/repositories.json"
            registry.parent.mkdir(parents=True)
            repos = registry_payload(discover_repositories(root, max_depth=2))
            for entry in repos["repositories"]:
                entry["included"] = entry["relative_path"] == "backend"
            registry.write_text(json.dumps(repos), encoding="utf-8")

            roots = workspace_roots(
                root,
                {"workspace": {"registry": "ai-workspace/config/repositories.json", "roots": [], "max_roots": 4}},
            )
            self.assertEqual(roots, [root.resolve(), backend.resolve()])
            self.assertNotIn(frontend.resolve(), roots)

    def test_duplicate_repository_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "ai-workspace/config/repositories.json"
            registry.parent.mkdir(parents=True)
            duplicate = {
                "name": "api",
                "relative_path": "api",
                "remote_identity": "github.com/acme/api",
                "included": True,
                "reason": "manual",
            }
            registry.write_text(
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

    def test_real_git_worktree_gitdir_file_is_supported_when_git_exists(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/acme/repo.git"],
                cwd=repo,
                check=True,
            )
            (repo / "file.txt").write_text("ok\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

            found = {item.relative_path: item for item in discover_repositories(root, max_depth=1)}
            self.assertIn("repo-wt", found)
            worktree_spec = found["repo-wt"]
            self.assertEqual(worktree_spec.remote_identity, "github.com/acme/repo")
            self.assertEqual(worktree_spec.head_ref, "refs/heads/worktree-test")
            self.assertEqual(worktree_spec.head_sha, expected_head)


if __name__ == "__main__":
    unittest.main()
