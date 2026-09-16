from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_workflow.bootstrap import setup


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class RepositoryHygieneTests(unittest.TestCase):
    def _git(self, root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _init_repo(self, root: Path) -> None:
        self._git(root, "init")
        self._git(root, "config", "user.email", "ci@example.invalid")
        self._git(root, "config", "user.name", "AI Workflow CI")
        (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        self._git(root, "add", "tracked.txt")
        self._git(root, "commit", "-m", "fixture")

    def _common_exclude(self, root: Path) -> Path:
        raw = self._git(root, "rev-parse", "--git-common-dir").stdout.strip()
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        return path.resolve() / "info" / "exclude"

    def _is_ignored(self, root: Path, relative: str) -> bool:
        proc = self._git(
            root,
            "check-ignore",
            "--no-index",
            "-q",
            relative,
            check=False,
        )
        return proc.returncode == 0

    def test_project_gitignore_covers_repository_pollution_classes(self):
        root = Path(__file__).resolve().parents[1]
        ignored = [
            "build/wheel.tmp",
            "dist/package.whl",
            "pkg.egg-info/PKG-INFO",
            ".eggs/cache",
            ".coverage",
            ".coverage.worker",
            "coverage.xml",
            "htmlcov/index.html",
            ".pytest_cache/v/cache/nodeids",
            ".mypy_cache/3.14/cache",
            ".ruff_cache/0.14/cache",
            ".hypothesis/examples/blob",
            "junit-results.xml",
            ".DS_Store",
            "Thumbs.db",
            ".idea/workspace.xml",
            ".vscode/settings.json",
            ".env",
            ".env.local",
            "private.pem",
            "private.key",
            "credentials/token.json",
            "secrets/local.txt",
            ".code-review-graph/graph.db",
            ".ai/local.json",
            "ai-workspace/code-review-graph/repo/graph.db",
            "ai-workspace/generated/index-state.json",
            "ai-workspace/memory/decisions.jsonl",
            "ai-workspace/config/repositories.json",
            "runtime.log",
        ]
        for relative in ignored:
            with self.subTest(relative=relative):
                self.assertTrue(
                    self._is_ignored(root, relative),
                    f"{relative} must be ignored",
                )

        allowed = [
            ".env.example",
            "ai-workspace/generated/.gitkeep",
            "ai-workspace/memory/README.md",
            "ai-workspace/config/control-plane.json",
        ]
        for relative in allowed:
            with self.subTest(relative=relative):
                self.assertFalse(
                    self._is_ignored(root, relative),
                    f"{relative} must remain trackable",
                )

    def test_setup_installs_idempotent_git_local_excludes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._init_repo(root)
            exclude = self._common_exclude(root)
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text(
                "# user local rule\n/private-user-file\n",
                encoding="utf-8",
            )

            first = setup(
                root,
                "Demo",
                index_mode="none",
                sync_crg=False,
            )
            first_text = exclude.read_text(encoding="utf-8")

            self.assertIn("# user local rule", first_text)
            self.assertIn("/private-user-file", first_text)
            self.assertEqual(
                first_text.count("# >>> ai-workflow local state >>>"),
                1,
            )
            self.assertEqual(
                first_text.count("# <<< ai-workflow local state <<<"),
                1,
            )
            for pattern in (
                "/ai-workspace/config/repositories.json",
                "/ai-workspace/generated/",
                "/ai-workspace/indexes/",
                "/ai-workspace/code-review-graph/",
                "/ai-workspace/memory/",
            ):
                self.assertIn(pattern, first_text)

            self.assertIn("repository_hygiene", first)
            self.assertTrue(
                first["repository_hygiene"]["local_excludes"]["installed"]
            )
            self.assertTrue(
                self._is_ignored(
                    root,
                    "ai-workspace/config/repositories.json",
                )
            )
            self.assertTrue(
                self._is_ignored(
                    root,
                    "ai-workspace/generated/index-state.json",
                )
            )
            self.assertFalse(
                self._is_ignored(
                    root,
                    "ai-workspace/config/control-plane.json",
                )
            )

            second = setup(
                root,
                "Demo",
                index_mode="none",
                sync_crg=False,
            )
            second_text = exclude.read_text(encoding="utf-8")
            self.assertEqual(
                second_text.count("# >>> ai-workflow local state >>>"),
                1,
            )
            self.assertEqual(first_text, second_text)
            self.assertFalse(
                second["repository_hygiene"]["local_excludes"]["changed"]
            )

    def test_setup_uses_common_exclude_for_linked_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            primary = base / "primary"
            linked = base / "linked"
            primary.mkdir()
            self._init_repo(primary)
            self._git(primary, "worktree", "add", str(linked))

            setup(
                linked,
                "Linked",
                index_mode="none",
                sync_crg=False,
            )

            primary_exclude = self._common_exclude(primary)
            linked_exclude = self._common_exclude(linked)
            self.assertEqual(primary_exclude, linked_exclude)
            text = linked_exclude.read_text(encoding="utf-8")
            self.assertIn("# >>> ai-workflow local state >>>", text)
            self.assertTrue(
                self._is_ignored(
                    linked,
                    "ai-workspace/config/repositories.json",
                )
            )

    def test_setup_non_git_workspace_does_not_create_git_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = setup(
                root,
                "Plain",
                index_mode="none",
                sync_crg=False,
            )
            self.assertFalse((root / ".git").exists())
            self.assertIn("repository_hygiene", result)
            self.assertFalse(
                result["repository_hygiene"]["local_excludes"]["applicable"]
            )


if __name__ == "__main__":
    unittest.main()
