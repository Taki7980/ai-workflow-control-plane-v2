from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import ai_workflow.repository_registry as repository_registry_module
from ai_workflow.repository_registry import (
    discover_repositories,
    load_registry,
    refresh_registry,
    registry_payload,
    remote_identity,
    repository_id,
    set_repository_included,
    workspace_registry_fingerprint,
)
from ai_workflow.workspace import workspace_roots
from ai_workflow.workspace_state import aggregate_workspace_fingerprint


class RepositoryRegistryTests(unittest.TestCase):
    def _git_repo(self, parent: Path, name: str, remote: str, head: str = "a" * 40) -> Path:
        repo = parent / name
        repo.mkdir(parents=True)
        git_dir = repo / ".git"
        (git_dir / "refs" / "heads").mkdir(parents=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "refs" / "heads" / "main").write_text(head + "\n", encoding="utf-8")
        (git_dir / "config").write_text(
            f'[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = {remote}\n',
            encoding="utf-8",
        )
        return repo

    def _real_git_repo(self, parent: Path, name: str, remote: str, content: str) -> Path:
        repo = parent / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True)
        (repo / "file.txt").write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return repo

    def test_remote_identity_removes_credentials_normalizes_host_and_preserves_path_case(self):
        self.assertEqual(
            remote_identity("https://token@example.com/Taki7980/Repo.git"),
            "example.com/Taki7980/Repo",
        )
        self.assertEqual(
            remote_identity("git@GITHUB.com:Taki7980/Repo.git"),
            "github.com/Taki7980/Repo",
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

    def test_registry_requires_explicit_review_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git_repo(root, "api", "https://github.com/acme/api.git")
            registry = root / "ai-workspace/config/repositories.json"
            registry.parent.mkdir(parents=True)
            payload = registry_payload(discover_repositories(root, max_depth=1))
            payload["repositories"][0]["included"] = True

            payload["review_required"] = False
            registry.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_registry(root), [])

            payload.pop("review_required")
            registry.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_registry(root), [])

    def test_refresh_migrates_legacy_lowercase_identity_without_preserving_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git_repo(root, "api", "https://example.com/Team/Repo.git")
            registry = root / "ai-workspace/config/repositories.json"
            registry.parent.mkdir(parents=True)
            legacy_identity = "example.com/team/repo"
            registry.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "repositories": [
                            {
                                "repository_id": repository_id("api", legacy_identity),
                                "name": "api",
                                "relative_path": "api",
                                "git_dir": "api/.git",
                                "remote_identity": legacy_identity,
                                "head_ref": "refs/heads/main",
                                "head_sha": "a" * 40,
                                "included": True,
                                "reason": "manual",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            refreshed = refresh_registry(root, max_depth=1)
            self.assertEqual(refreshed["accepted"], 0)
            self.assertEqual(refreshed["repositories"][0]["remote_identity"], "example.com/Team/Repo")
            self.assertNotEqual(refreshed["repositories"][0]["repository_id"], repository_id("api", legacy_identity))

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

    def test_registry_mutation_waits_for_interprocess_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git_repo(root, "api", "https://github.com/acme/api.git")
            refresh_registry(root, max_depth=1)
            registry = root / "ai-workspace/config/repositories.json"
            started = root / "child-started"
            finished = root / "child-finished"
            registry_lock = getattr(repository_registry_module, "_registry_lock")
            script = (
                "from pathlib import Path\n"
                "import sys\n"
                "from ai_workflow.repository_registry import set_repository_included\n"
                "root = Path(sys.argv[1])\n"
                "Path(sys.argv[2]).write_text('started', encoding='utf-8')\n"
                "set_repository_included(root, 'api', True)\n"
                "Path(sys.argv[3]).write_text('finished', encoding='utf-8')\n"
            )
            process = None
            try:
                with registry_lock(registry):
                    process = subprocess.Popen(
                        [sys.executable, "-c", script, str(root), str(started), str(finished)],
                        cwd=Path.cwd(),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    deadline = time.monotonic() + 5.0
                    while not started.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(started.exists(), "child process did not start")
                    time.sleep(0.15)
                    self.assertFalse(finished.exists(), "registry mutation bypassed the lock")
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, msg=f"stdout={stdout}\nstderr={stderr}")
                self.assertTrue(finished.exists())
                self.assertTrue(load_registry(root)[0].included)
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def test_legacy_root_order_does_not_change_aggregate_fingerprint_when_identity_ties(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            workspace = base / "workspace"
            workspace.mkdir()
            remote = "https://example.com/Team/Repo.git"
            first = self._real_git_repo(base / "one", "api", remote, "one\n")
            second = self._real_git_repo(base / "two", "api", remote, "two\n")
            forward = {
                "workspace": {
                    "roots": [str(first), str(second)],
                    "max_roots": 3,
                    "registry": "ai-workspace/config/repositories.json",
                }
            }
            reverse = {
                "workspace": {
                    "roots": [str(second), str(first)],
                    "max_roots": 3,
                    "registry": "ai-workspace/config/repositories.json",
                }
            }

            forward_state = aggregate_workspace_fingerprint(workspace, forward)
            reverse_state = aggregate_workspace_fingerprint(workspace, reverse)
            self.assertNotEqual(
                forward_state["repositories"][1]["fingerprint"],
                forward_state["repositories"][2]["fingerprint"],
            )
            self.assertEqual(forward_state["fingerprint"], reverse_state["fingerprint"])

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
