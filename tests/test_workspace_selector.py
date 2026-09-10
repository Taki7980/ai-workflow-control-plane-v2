from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config, validate_config
from ai_workflow.workspace_selector import (
    RepositoryCandidate,
    build_repository_candidates,
    select_repositories,
)


class WorkspaceSelectorTests(unittest.TestCase):
    def _candidate(
        self,
        root: Path,
        repo_id: str,
        repo_path: str,
        *,
        changed: tuple[str, ...] = (),
        primary: bool = False,
        remote: str | None = None,
    ) -> RepositoryCandidate:
        return RepositoryCandidate(
            root=root,
            repository_id=repo_id,
            repository_path=repo_path,
            remote_identity=remote,
            fingerprint=f"fp-{repo_id}",
            changed_files=changed,
            is_primary=primary,
        )

    def _write_indexes(self, root: Path, symbols: list[dict], endpoints: list[dict] | None = None) -> None:
        generated = root / "ai-workspace" / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        (generated / "symbol-index.jsonl").write_text(
            "\n".join(json.dumps(row) for row in symbols) + ("\n" if symbols else ""),
            encoding="utf-8",
        )
        (generated / "endpoint-index.jsonl").write_text(
            "\n".join(json.dumps(row) for row in (endpoints or [])) + ("\n" if endpoints else ""),
            encoding="utf-8",
        )

    def test_config_defaults_include_bounded_workspace_retrieval(self):
        self.assertEqual(
            default_config()["workspace"]["retrieval"],
            {
                "max_selected_repositories": 3,
                "max_workers": 3,
                "deadline_seconds": 12,
            },
        )

    def test_config_rejects_invalid_workspace_retrieval_values(self):
        invalid = [
            ("max_selected_repositories", 0),
            ("max_selected_repositories", True),
            ("max_workers", -1),
            ("max_workers", False),
            ("deadline_seconds", 0),
            ("deadline_seconds", True),
            ("deadline_seconds", "12"),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                config = default_config()
                config["workspace"]["retrieval"][field] = value
                with self.assertRaises(ValueError):
                    validate_config(config)

    def test_candidate_builder_partitions_explicit_changed_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            backend = root / "backend"
            backend.mkdir()
            aggregate = {
                "repositories": [
                    {
                        "root": str(root),
                        "repository_id": "root-id",
                        "relative_path": ".",
                        "remote_identity": "github.com/acme/workspace",
                        "fingerprint": "root-fp",
                    },
                    {
                        "root": str(backend),
                        "repository_id": "backend-id",
                        "relative_path": "backend",
                        "remote_identity": "github.com/acme/backend",
                        "fingerprint": "backend-fp",
                    },
                ]
            }
            with patch("ai_workflow.workspace_selector.workspace_roots", return_value=[root, backend]), patch(
                "ai_workflow.workspace_selector.aggregate_workspace_fingerprint", return_value=aggregate
            ), patch("ai_workflow.workspace_selector.is_git_repository", return_value=True):
                candidates = build_repository_candidates(
                    root,
                    {"workspace": {}},
                    ["backend/internal/payments.go", "README.md"],
                )

            by_path = {candidate.repository_path: candidate for candidate in candidates}
            self.assertEqual(by_path["backend"].changed_files, ("internal/payments.go",))
            self.assertEqual(by_path["."].changed_files, ("README.md",))

    def test_candidate_builder_detects_changes_per_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            backend = root / "backend"
            backend.mkdir()
            aggregate = {
                "repositories": [
                    {"root": str(root), "repository_id": "root-id", "relative_path": ".", "remote_identity": None, "fingerprint": "root-fp"},
                    {"root": str(backend), "repository_id": "backend-id", "relative_path": "backend", "remote_identity": None, "fingerprint": "backend-fp"},
                ]
            }

            def changed(repo: Path) -> list[str]:
                return ["root.py"] if repo == root else ["backend.py"]

            with patch("ai_workflow.workspace_selector.workspace_roots", return_value=[root, backend]), patch(
                "ai_workflow.workspace_selector.aggregate_workspace_fingerprint", return_value=aggregate
            ), patch("ai_workflow.workspace_selector.is_git_repository", return_value=True), patch(
                "ai_workflow.workspace_selector.detect_changed_files", side_effect=changed
            ):
                candidates = build_repository_candidates(root, {"workspace": {}}, None)

            by_path = {candidate.repository_path: candidate for candidate in candidates}
            self.assertEqual(by_path["."].changed_files, ("root.py",))
            self.assertEqual(by_path["backend"].changed_files, ("backend.py",))

    def test_clear_secondary_match_outranks_primary_and_skips_unrelated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            self._write_indexes(
                root,
                [
                    {"symbol": "RootConfig", "file": "config.py"},
                    {"symbol": "ProcessPayment", "file": "backend/payments/service.py"},
                    {"symbol": "RenderHome", "file": "frontend/home.ts"},
                ],
            )
            candidates = [
                self._candidate(root, "root-id", ".", primary=True, remote="github.com/acme/root"),
                self._candidate(backend, "backend-id", "backend", remote="github.com/acme/backend"),
                self._candidate(frontend, "frontend-id", "frontend", remote="github.com/acme/frontend"),
            ]
            selected = select_repositories(root, candidates, "fix ProcessPayment payment failure")
            self.assertEqual([row.candidate.repository_id for row in selected if row.selected], ["backend-id"])
            self.assertFalse(next(row for row in selected if row.candidate.repository_id == "root-id").selected)
            self.assertFalse(next(row for row in selected if row.candidate.repository_id == "frontend-id").selected)

    def test_primary_prior_only_wins_ambiguous_multi_repo_task(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            child = root / "child"
            child.mkdir()
            self._write_indexes(root, [])
            candidates = [
                self._candidate(root, "root-id", ".", primary=True),
                self._candidate(child, "child-id", "child"),
            ]
            rows = select_repositories(root, candidates, "investigate issue")
            self.assertEqual([row.candidate.repository_id for row in rows if row.selected], ["root-id"])

    def test_symbol_and_endpoint_hints_select_owning_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            self._write_indexes(
                root,
                [
                    {"symbol": "ProcessPayment", "file": "backend/payments.py"},
                    {"symbol": "PaymentForm", "file": "frontend/payment.ts"},
                ],
                [
                    {"method": "POST", "path": "/api/payments", "file": "backend/routes.py"},
                    {"method": "GET", "path": "/ui/payment", "file": "frontend/routes.ts"},
                ],
            )
            candidates = [
                self._candidate(backend, "backend-id", "backend"),
                self._candidate(frontend, "frontend-id", "frontend"),
            ]
            by_symbol = select_repositories(root, candidates, "change handler", symbol="ProcessPayment")
            self.assertEqual([r.candidate.repository_id for r in by_symbol if r.selected], ["backend-id"])
            by_endpoint = select_repositories(root, candidates, "change route", endpoint="/api/payments")
            self.assertEqual([r.candidate.repository_id for r in by_endpoint if r.selected], ["backend-id"])

    def test_changed_file_lifts_owning_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            backend = root / "backend"
            frontend = root / "frontend"
            backend.mkdir()
            frontend.mkdir()
            self._write_indexes(root, [])
            candidates = [
                self._candidate(backend, "backend-id", "backend", changed=("internal/payments.py",)),
                self._candidate(frontend, "frontend-id", "frontend", changed=("home.ts",)),
            ]
            rows = select_repositories(root, candidates, "fix payments change")
            self.assertEqual([r.candidate.repository_id for r in rows if r.selected], ["backend-id"])
            self.assertIn("changed_file", next(r for r in rows if r.selected).reasons)

    def test_selection_is_input_order_independent_and_capped_at_three(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            self._write_indexes(root, [])
            candidates = [
                self._candidate(root / f"repo-{i}", f"id-{i}", f"payment-repo-{i}")
                for i in range(5)
            ]
            first = select_repositories(root, candidates, "payment repository")
            second = select_repositories(root, list(reversed(candidates)), "payment repository")
            first_ids = [r.candidate.repository_id for r in first if r.selected]
            second_ids = [r.candidate.repository_id for r in second if r.selected]
            self.assertEqual(first_ids, second_ids)
            self.assertEqual(len(first_ids), 3)


if __name__ == "__main__":
    unittest.main()
