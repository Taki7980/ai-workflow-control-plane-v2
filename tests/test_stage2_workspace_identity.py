from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ai_workflow.bootstrap import setup
from ai_workflow.cli import build_parser
from ai_workflow.config import default_config
from ai_workflow.repository_registry import (
    discover_repositories,
    load_registry,
    refresh_registry,
    registry_payload,
    registry_summary,
    remote_identity,
    repository_id,
    set_repository_included,
)
from ai_workflow.workspace import workspace_roots
from ai_workflow.workspace_state import (
    aggregate_workspace_fingerprint,
    repository_fingerprint,
)


class Stage2WorkspaceIdentityTests(unittest.TestCase):
    def _fake_git_repo(self, parent: Path, name: str, remote: str, head: str = "a" * 40) -> Path:
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

    def _real_git_repo(self, parent: Path, name: str = "repo") -> Path:
        repo = parent / name
        repo.mkdir(parents=True)
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
        (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return repo

    def _write_registry(self, root: Path, repositories: list[dict]) -> Path:
        path = root / "ai-workspace/config/repositories.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "review_required": True, "repositories": repositories}),
            encoding="utf-8",
        )
        return path

    def _config(self) -> dict:
        config = default_config()
        config["workspace"]["max_roots"] = 10
        return config

    def _run_cli(self, root: Path, *arguments: str) -> dict:
        args = build_parser().parse_args(["--root", str(root), *arguments])
        with redirect_stdout(io.StringIO()) as output:
            args.func(args)
        return json.loads(output.getvalue())

    def test_registry_payload_never_persists_raw_remote_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fake_git_repo(
                root,
                "api",
                "https://token:secret@example.com/acme/api.git",
            )
            payload = registry_payload(discover_repositories(root, max_depth=1))
            encoded = json.dumps(payload)
            self.assertNotIn("token", encoded)
            self.assertNotIn("secret", encoded)
            self.assertNotIn("remote_url", encoded)
            entry = payload["repositories"][0]
            self.assertEqual(entry["remote_identity"], "example.com/acme/api")
            self.assertEqual(
                entry["repository_id"],
                repository_id("api", "example.com/acme/api"),
            )

    def test_invalid_registry_versions_and_shapes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "ai-workspace/config/repositories.json"
            path.parent.mkdir(parents=True)
            for payload in (
                "not-json",
                json.dumps({"version": 99, "repositories": []}),
                json.dumps({"version": 1, "repositories": {}}),
            ):
                path.write_text(payload, encoding="utf-8")
                self.assertEqual(load_registry(root), [])

    def test_refresh_preserves_only_unchanged_repository_identity_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._fake_git_repo(root, "api", "https://github.com/acme/api.git")
            refresh_registry(root, max_depth=1)
            set_repository_included(root, "api", True)
            refreshed = refresh_registry(root, max_depth=1)
            self.assertEqual(refreshed["accepted"], 1)

            (repo / ".git/config").write_text(
                '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = https://github.com/other/api.git\n',
                encoding="utf-8",
            )
            changed = refresh_registry(root, max_depth=1)
            self.assertEqual(changed["accepted"], 0)
            self.assertEqual(
                changed["repositories"][0]["remote_identity"],
                "github.com/other/api",
            )

    def test_ambiguous_selector_fails_without_writing_registry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fake_git_repo(root / "services", "api", "https://github.com/acme/service-api.git")
            self._fake_git_repo(root / "apps", "api", "https://github.com/acme/app-api.git")
            refresh_registry(root, max_depth=2)
            path = root / "ai-workspace/config/repositories.json"
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                set_repository_included(root, "api", True)
            self.assertEqual(before, path.read_bytes())

            result = set_repository_included(root, "services/api", True)
            self.assertEqual(result["accepted"], 1)
            self.assertEqual(result["changed"]["relative_path"], "services/api")

    def test_registry_paths_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            root.mkdir()
            outside = self._fake_git_repo(base, "outside", "https://github.com/acme/outside.git")
            self._write_registry(
                root,
                [
                    {
                        "name": "outside-parent",
                        "relative_path": "../outside",
                        "remote_identity": "github.com/acme/outside",
                        "included": True,
                        "reason": "manual",
                    },
                    {
                        "name": "outside-absolute",
                        "relative_path": str(outside.resolve()),
                        "remote_identity": "github.com/acme/outside",
                        "included": True,
                        "reason": "manual",
                    },
                ],
            )
            self.assertEqual(workspace_roots(root, self._config()), [root.resolve()])

    def test_symlink_escape_and_non_git_directory_are_not_activated(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "workspace"
            root.mkdir()
            outside = self._fake_git_repo(base, "outside", "https://github.com/acme/outside.git")
            (root / "plain").mkdir()
            entries = [
                {
                    "name": "plain",
                    "relative_path": "plain",
                    "remote_identity": None,
                    "included": True,
                    "reason": "manual",
                }
            ]
            link = root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                pass
            else:
                entries.append(
                    {
                        "name": "link",
                        "relative_path": "link",
                        "remote_identity": "github.com/acme/outside",
                        "included": True,
                        "reason": "manual",
                    }
                )
            self._write_registry(root, entries)
            self.assertEqual(workspace_roots(root, self._config()), [root.resolve()])

    def test_registry_summary_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._fake_git_repo(root, "zeta", "https://github.com/acme/zeta.git")
            self._fake_git_repo(root, "alpha", "https://github.com/acme/alpha.git")
            first = refresh_registry(root, max_depth=1)
            second = registry_summary(root)
            self.assertEqual(first["fingerprint"], second["fingerprint"])
            self.assertEqual(
                [item["relative_path"] for item in second["repositories"]],
                ["alpha", "zeta"],
            )

    def test_repository_fingerprint_is_checkout_path_independent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            first = self._fake_git_repo(base / "one", "api", "https://github.com/acme/api.git")
            second = self._fake_git_repo(base / "two", "api", "https://github.com/acme/api.git")
            first_state = repository_fingerprint(first, "api", "github.com/acme/api")
            second_state = repository_fingerprint(second, "api", "github.com/acme/api")
            self.assertNotEqual(first_state["root"], second_state["root"])
            self.assertEqual(first_state["fingerprint"], second_state["fingerprint"])

    def test_repository_fingerprint_tracks_dirty_content_not_only_dirty_boolean(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            repo = self._real_git_repo(Path(td))
            clean = repository_fingerprint(repo, ".", "github.com/acme/repo")
            self.assertFalse(clean["git_dirty"])

            (repo / "tracked.txt").write_text("two\n", encoding="utf-8")
            dirty_one = repository_fingerprint(repo, ".", "github.com/acme/repo")
            self.assertTrue(dirty_one["git_dirty"])
            self.assertNotEqual(clean["fingerprint"], dirty_one["fingerprint"])

            (repo / "tracked.txt").write_text("three\n", encoding="utf-8")
            dirty_two = repository_fingerprint(repo, ".", "github.com/acme/repo")
            self.assertNotEqual(dirty_one["git_worktree_sha256"], dirty_two["git_worktree_sha256"])
            self.assertNotEqual(dirty_one["fingerprint"], dirty_two["fingerprint"])

            (repo / "new.txt").write_text("alpha\n", encoding="utf-8")
            untracked_one = repository_fingerprint(repo, ".", "github.com/acme/repo")
            (repo / "new.txt").write_text("beta\n", encoding="utf-8")
            untracked_two = repository_fingerprint(repo, ".", "github.com/acme/repo")
            self.assertNotEqual(
                untracked_one["git_worktree_sha256"],
                untracked_two["git_worktree_sha256"],
            )

    def test_aggregate_workspace_fingerprint_is_path_independent_and_ordered(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            snapshots = []
            for folder in ("one", "two"):
                root = base / folder
                root.mkdir()
                self._fake_git_repo(root, "frontend", "https://github.com/acme/frontend.git")
                self._fake_git_repo(root, "backend", "https://github.com/acme/backend.git")
                refresh_registry(root, max_depth=1)
                set_repository_included(root, "frontend", True)
                set_repository_included(root, "backend", True)
                snapshots.append(aggregate_workspace_fingerprint(root, self._config()))

            self.assertNotEqual(snapshots[0]["root"], snapshots[1]["root"])
            self.assertEqual(snapshots[0]["fingerprint"], snapshots[1]["fingerprint"])
            self.assertEqual(
                [item["relative_path"] for item in snapshots[0]["repositories"]],
                [".", "backend", "frontend"],
            )

    def test_aggregate_workspace_fingerprint_changes_when_one_repo_changes(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "workspace"
            root.mkdir()
            backend = self._real_git_repo(root, "backend")
            refresh_registry(root, max_depth=1)
            set_repository_included(root, "backend", True)
            before = aggregate_workspace_fingerprint(root, self._config())["fingerprint"]
            (backend / "tracked.txt").write_text("changed\n", encoding="utf-8")
            after = aggregate_workspace_fingerprint(root, self._config())["fingerprint"]
            self.assertNotEqual(before, after)

    def test_repo_cli_refresh_include_list_and_exclude(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup(root, "Demo", index_mode="none", discover=False)
            self._fake_git_repo(root, "api", "https://github.com/acme/api.git")

            refreshed = self._run_cli(root, "repos", "refresh", "--discover-depth", "1")
            self.assertEqual(refreshed["discovered"], 1)
            self.assertEqual(refreshed["accepted"], 0)

            included = self._run_cli(root, "repos", "include", "api")
            self.assertEqual(included["accepted"], 1)
            self.assertEqual(included["changed"]["action"], "included")

            listed = self._run_cli(root, "repos", "list")
            self.assertEqual(listed["accepted"], 1)
            self.assertNotIn("remote_url", json.dumps(listed))

            excluded = self._run_cli(root, "repos", "exclude", "api")
            self.assertEqual(excluded["accepted"], 0)
            self.assertEqual(excluded["changed"]["action"], "excluded")

    def test_repo_cli_ambiguous_selector_fails_without_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup(root, "Demo", index_mode="none", discover=False)
            self._fake_git_repo(root / "services", "api", "https://github.com/acme/service-api.git")
            self._fake_git_repo(root / "apps", "api", "https://github.com/acme/app-api.git")
            self._run_cli(root, "repos", "refresh", "--discover-depth", "2")
            path = root / "ai-workspace/config/repositories.json"
            before = path.read_bytes()
            args = build_parser().parse_args(
                ["--root", str(root), "repos", "include", "api"]
            )
            with self.assertRaisesRegex(SystemExit, "ambiguous"):
                with redirect_stdout(io.StringIO()):
                    args.func(args)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
