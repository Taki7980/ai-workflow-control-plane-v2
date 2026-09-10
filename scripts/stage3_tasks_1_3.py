from __future__ import annotations

import argparse
from pathlib import Path

SELECTOR_TESTS = r'''from __future__ import annotations

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
'''

BUDGET_TESTS = r'''from __future__ import annotations

import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.workspace_budget import allocate_repository_budgets
from ai_workflow.workspace_selector import RepositoryCandidate, RepositorySelection


class WorkspaceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.parent = ContextBudget(
            estimated_tokens=1000,
            output_tokens=300,
            context_chars=4000,
            source_chars={"hot_cache": 600, "lightweight": 1200, "crg": 1600, "source_fallback": 600},
        )

    def _selection(self, index: int, score: float, *, selected: bool = True) -> RepositorySelection:
        candidate = RepositoryCandidate(
            root=Path(f"/tmp/repo-{index}"),
            repository_id=f"repo-{index}",
            repository_path=f"repo-{index}",
            remote_identity=None,
            fingerprint=f"fp-{index}",
            changed_files=(),
            is_primary=index == 0,
        )
        return RepositorySelection(candidate, score, index + 1, selected, ("index_match",))

    def test_single_repo_gets_exact_parent_budget(self):
        budgets = allocate_repository_budgets(self.parent, [self._selection(0, 3.0)])
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0].context, self.parent)
        self.assertEqual(budgets[0].ratio, 1.0)

    def test_multi_repo_rank_one_gets_at_least_half_and_global_budget_is_conserved(self):
        selections = [self._selection(0, 1.0), self._selection(1, 1.0), self._selection(2, 1.0)]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertGreaterEqual(budgets[0].context.context_chars, self.parent.context_chars // 2)
        self.assertLessEqual(sum(b.context.context_chars for b in budgets), self.parent.context_chars)
        self.assertLessEqual(sum(b.context.estimated_tokens for b in budgets), self.parent.estimated_tokens)
        for source, parent_chars in self.parent.source_chars.items():
            self.assertLessEqual(sum(b.context.source_chars[source] for b in budgets), parent_chars)

    def test_zero_or_skipped_repository_receives_no_allocation(self):
        selections = [
            self._selection(0, 4.0),
            self._selection(1, 0.0),
            self._selection(2, 2.0, selected=False),
        ]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertEqual([b.repository_id for b in budgets], ["repo-0"])

    def test_rounding_and_input_order_are_deterministic(self):
        selections = [self._selection(0, 5.0), self._selection(1, 3.0), self._selection(2, 2.0)]
        first = allocate_repository_budgets(self.parent, selections)
        second = allocate_repository_budgets(self.parent, list(reversed(selections)))
        self.assertEqual(
            [(b.repository_id, b.context.context_chars, b.context.source_chars) for b in first],
            [(b.repository_id, b.context.context_chars, b.context.source_chars) for b in second],
        )

    def test_ten_repository_fixture_cannot_multiply_parent_budget(self):
        selections = [self._selection(i, float(10 - i)) for i in range(10)]
        budgets = allocate_repository_budgets(self.parent, selections)
        self.assertEqual(len(budgets), 10)
        self.assertEqual(sum(b.context.context_chars for b in budgets), self.parent.context_chars)
        for source, parent_chars in self.parent.source_chars.items():
            self.assertEqual(sum(b.context.source_chars[source] for b in budgets), parent_chars)


if __name__ == "__main__":
    unittest.main()
'''

SELECTOR_MODULE = r'''from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context_broker import detect_changed_files
from .math_retrieval import tokenize
from .repository_registry import is_git_repository, repository_id
from .workspace import workspace_roots
from .workspace_state import aggregate_workspace_fingerprint

_LOW_INFORMATION_QUERY_TOKENS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does",
    "for", "from", "how", "in", "is", "it", "of", "on", "or", "should",
    "the", "to", "we", "where", "whether", "with",
})
_EXPLICIT_HINT_WEIGHT = 100.0
_CHANGED_FILE_WEIGHT = 40.0
_IDENTITY_WEIGHT = 12.0
_INDEX_WEIGHT = 3.0
_PRIMARY_PRIOR = 0.25


@dataclass(frozen=True)
class RepositoryCandidate:
    root: Path
    repository_id: str
    repository_path: str
    remote_identity: str | None
    fingerprint: str
    changed_files: tuple[str, ...]
    is_primary: bool


@dataclass(frozen=True)
class RepositorySelection:
    candidate: RepositoryCandidate
    score: float
    rank: int
    selected: bool
    reasons: tuple[str, ...]


def _meaningful_tokens(text: str) -> set[str]:
    return {token for token in tokenize(text) if token not in _LOW_INFORMATION_QUERY_TOKENS}


def _fallback_repository_path(workspace_root: Path, repo_root: Path) -> str:
    if repo_root == workspace_root:
        return "."
    try:
        return repo_root.relative_to(workspace_root).as_posix()
    except ValueError:
        return f"legacy:{repo_root.name.casefold()}"


def _partition_explicit_changes(
    candidates: list[tuple[Path, str]],
    changed_files: list[str],
) -> dict[str, list[str]]:
    out = {repo_path: [] for _, repo_path in candidates}
    child_paths = sorted(
        (repo_path for _, repo_path in candidates if repo_path != "." and not repo_path.startswith("legacy:")),
        key=lambda value: (-len(value), value.casefold()),
    )
    has_primary = "." in out
    for raw in changed_files:
        value = str(raw).replace("\\", "/").strip("/")
        if not value:
            continue
        owner = None
        local = value
        for repo_path in child_paths:
            prefix = repo_path.rstrip("/") + "/"
            if value.startswith(prefix):
                owner = repo_path
                local = value[len(prefix):]
                break
        if owner is None and has_primary:
            owner = "."
        if owner is not None and local:
            out[owner].append(local)
    return {key: sorted(set(values)) for key, values in out.items()}


def build_repository_candidates(
    workspace_root: Path,
    config: dict,
    explicit_changed_files: list[str] | None = None,
) -> list[RepositoryCandidate]:
    workspace_root = Path(workspace_root).resolve()
    roots = [Path(root).resolve() for root in workspace_roots(workspace_root, config)]
    git_roots = [root for root in roots if is_git_repository(root)]
    candidate_roots = git_roots or ([workspace_root] if workspace_root in roots else [])
    aggregate = aggregate_workspace_fingerprint(workspace_root, config)
    snapshots = {
        Path(str(item.get("root", ""))).resolve(): item
        for item in aggregate.get("repositories", [])
        if item.get("root")
    }
    identities: list[tuple[Path, str, dict[str, Any]]] = []
    for repo_root in candidate_roots:
        snapshot = snapshots.get(repo_root, {})
        repo_path = str(snapshot.get("relative_path") or _fallback_repository_path(workspace_root, repo_root))
        identities.append((repo_root, repo_path, snapshot))

    if explicit_changed_files is None:
        change_map = {
            repo_path: sorted(set(detect_changed_files(repo_root)))
            for repo_root, repo_path, _ in identities
        }
    else:
        change_map = _partition_explicit_changes(
            [(repo_root, repo_path) for repo_root, repo_path, _ in identities],
            explicit_changed_files,
        )

    candidates: list[RepositoryCandidate] = []
    for repo_root, repo_path, snapshot in identities:
        remote = snapshot.get("remote_identity")
        repo_id = str(snapshot.get("repository_id") or repository_id(repo_path, remote))
        candidates.append(
            RepositoryCandidate(
                root=repo_root,
                repository_id=repo_id,
                repository_path=repo_path,
                remote_identity=str(remote) if remote else None,
                fingerprint=str(snapshot.get("fingerprint") or ""),
                changed_files=tuple(change_map.get(repo_path, [])),
                is_primary=repo_root == workspace_root and is_git_repository(repo_root),
            )
        )
    return sorted(candidates, key=lambda item: (not item.is_primary, item.repository_id, item.repository_path.casefold()))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _candidate_rows(
    rows: list[dict[str, Any]],
    candidate: RepositoryCandidate,
    child_paths: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        file = str(row.get("file", "")).replace("\\", "/").lstrip("./")
        belongs = False
        if candidate.repository_path == ".":
            belongs = not any(file.startswith(path.rstrip("/") + "/") for path in child_paths)
        elif not candidate.repository_path.startswith("legacy:"):
            belongs = file.startswith(candidate.repository_path.rstrip("/") + "/")
        if belongs:
            out.append(row)
            if len(out) >= limit:
                break
    return out


def select_repositories(
    workspace_root: Path,
    candidates: list[RepositoryCandidate],
    query: str,
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
    max_selected: int = 3,
    max_index_candidates: int = 200,
) -> list[RepositorySelection]:
    if not candidates:
        return []
    workspace_root = Path(workspace_root).resolve()
    generated = workspace_root / "ai-workspace" / "generated"
    symbols = _jsonl(generated / "symbol-index.jsonl")
    endpoints = _jsonl(generated / "endpoint-index.jsonl")
    child_paths = tuple(
        sorted(
            candidate.repository_path
            for candidate in candidates
            if candidate.repository_path != "." and not candidate.repository_path.startswith("legacy:")
        )
    )
    query_tokens = _meaningful_tokens(query)
    scored: list[tuple[RepositoryCandidate, float, tuple[str, ...], bool]] = []
    for candidate in candidates:
        score = 0.0
        reasons: list[str] = []
        symbol_rows = _candidate_rows(symbols, candidate, child_paths, max_index_candidates)
        endpoint_rows = _candidate_rows(endpoints, candidate, child_paths, max_index_candidates)

        if symbol and any(str(row.get("symbol", "")).casefold() == symbol.casefold() for row in symbol_rows):
            score += _EXPLICIT_HINT_WEIGHT
            reasons.append("symbol_hint")
        if endpoint and any(endpoint.casefold() in str(row.get("path", "")).casefold() for row in endpoint_rows):
            score += _EXPLICIT_HINT_WEIGHT
            reasons.append("endpoint_hint")

        changed_tokens = _meaningful_tokens(" ".join(candidate.changed_files))
        if query_tokens & changed_tokens:
            score += _CHANGED_FILE_WEIGHT
            reasons.append("changed_file")

        identity_text = " ".join(filter(None, (candidate.repository_path, candidate.remote_identity or "")))
        identity_overlap = len(query_tokens & _meaningful_tokens(identity_text))
        if identity_overlap:
            score += _IDENTITY_WEIGHT * identity_overlap
            reasons.append("identity_match")

        best_index_overlap = 0
        for row in [*symbol_rows, *endpoint_rows]:
            row_text = " ".join(
                str(row.get(key, ""))
                for key in ("symbol", "method", "path", "file")
            )
            best_index_overlap = max(best_index_overlap, len(query_tokens & _meaningful_tokens(row_text)))
        if best_index_overlap:
            score += _INDEX_WEIGHT * best_index_overlap
            reasons.append("index_match")

        has_evidence = bool(reasons)
        if candidate.is_primary:
            score += _PRIMARY_PRIOR
            reasons.append("primary_prior")
        scored.append((candidate, score, tuple(reasons), has_evidence))

    ordered = sorted(scored, key=lambda row: (-row[1], row[0].repository_id, row[0].repository_path.casefold()))
    has_evidence = any(row[3] for row in ordered)
    selected_ids: set[str] = set()
    if len(ordered) == 1:
        selected_ids.add(ordered[0][0].repository_id)
    elif has_evidence:
        for candidate, score, reasons, evidence in ordered:
            if evidence and score > 0 and len(selected_ids) < max(1, int(max_selected)):
                selected_ids.add(candidate.repository_id)
    else:
        primary = next((row for row in ordered if row[0].is_primary), None)
        if primary is not None:
            selected_ids.add(primary[0].repository_id)

    result: list[RepositorySelection] = []
    for rank, (candidate, score, reasons, _) in enumerate(ordered, 1):
        selected = candidate.repository_id in selected_ids
        final_reasons = reasons if selected or reasons else ("no_relevant_signal",)
        result.append(RepositorySelection(candidate, score, rank, selected, final_reasons))
    return result
'''

BUDGET_MODULE = r'''from __future__ import annotations

import math
from dataclasses import dataclass

from .budget import ContextBudget
from .workspace_selector import RepositorySelection


@dataclass(frozen=True)
class RepositoryBudget:
    repository_id: str
    rank: int
    ratio: float
    context: ContextBudget


def _allocate_integers(total: int, weighted: list[tuple[str, float]]) -> dict[str, int]:
    if total <= 0 or not weighted:
        return {key: 0 for key, _ in weighted}
    weight_sum = sum(max(0.0, weight) for _, weight in weighted)
    if weight_sum <= 0:
        return {key: 0 for key, _ in weighted}
    raw = [(key, total * max(0.0, weight) / weight_sum) for key, weight in weighted]
    allocated = {key: int(math.floor(value)) for key, value in raw}
    remainder = total - sum(allocated.values())
    order = [key for key, _ in weighted]
    for index in range(remainder):
        allocated[order[index % len(order)]] += 1
    return allocated


def _ratios(selections: list[RepositorySelection]) -> list[tuple[str, float]]:
    ordered = sorted(selections, key=lambda row: (row.rank, row.candidate.repository_id))
    positive = [(row.candidate.repository_id, max(0.0, float(row.score))) for row in ordered]
    total = sum(weight for _, weight in positive)
    if total <= 0:
        return []
    ratios = [(repo_id, weight / total) for repo_id, weight in positive]
    if len(ratios) > 1 and ratios[0][1] < 0.5:
        tail_total = sum(value for _, value in ratios[1:])
        tail = [
            (repo_id, 0.5 * value / tail_total if tail_total > 0 else 0.0)
            for repo_id, value in ratios[1:]
        ]
        ratios = [(ratios[0][0], 0.5), *tail]
    return ratios


def allocate_repository_budgets(
    parent: ContextBudget,
    selections: list[RepositorySelection],
) -> list[RepositoryBudget]:
    selected = sorted(
        (row for row in selections if row.selected and row.score > 0),
        key=lambda row: (row.rank, row.candidate.repository_id),
    )
    if not selected:
        selected = sorted(
            (row for row in selections if row.selected),
            key=lambda row: (row.rank, row.candidate.repository_id),
        )
    if not selected:
        return []
    if len(selected) == 1:
        row = selected[0]
        return [RepositoryBudget(row.candidate.repository_id, row.rank, 1.0, parent)]

    ratio_pairs = _ratios(selected)
    if not ratio_pairs:
        equal = 1.0 / len(selected)
        ratio_pairs = [(row.candidate.repository_id, equal) for row in selected]
    ratio_map = dict(ratio_pairs)
    weighted = [(row.candidate.repository_id, ratio_map[row.candidate.repository_id]) for row in selected]
    context_alloc = _allocate_integers(parent.context_chars, weighted)
    token_alloc = _allocate_integers(parent.estimated_tokens, weighted)
    source_alloc = {
        source: _allocate_integers(chars, weighted)
        for source, chars in parent.source_chars.items()
    }

    budgets: list[RepositoryBudget] = []
    for row in selected:
        repo_id = row.candidate.repository_id
        source_chars = {source: allocations[repo_id] for source, allocations in source_alloc.items()}
        budgets.append(
            RepositoryBudget(
                repository_id=repo_id,
                rank=row.rank,
                ratio=context_alloc[repo_id] / parent.context_chars if parent.context_chars else 0.0,
                context=ContextBudget(
                    estimated_tokens=token_alloc[repo_id],
                    output_tokens=0,
                    context_chars=context_alloc[repo_id],
                    source_chars=source_chars,
                ),
            )
        )
    return budgets
'''


def write_tests() -> None:
    Path('tests/test_workspace_selector.py').write_text(SELECTOR_TESTS, encoding='utf-8')
    Path('tests/test_workspace_budget.py').write_text(BUDGET_TESTS, encoding='utf-8')


def patch_config() -> None:
    path = Path('ai_workflow/config.py')
    text = path.read_text(encoding='utf-8')
    old = '''        "discovery": {"max_depth": 3, "require_acceptance": True},\n    },'''
    new = '''        "discovery": {"max_depth": 3, "require_acceptance": True},\n        "retrieval": {\n            "max_selected_repositories": 3,\n            "max_workers": 3,\n            "deadline_seconds": 12,\n        },\n    },'''
    if '"max_selected_repositories": 3' not in text:
        if old not in text:
            raise SystemExit('workspace default marker not found')
        text = text.replace(old, new, 1)
    validation_anchor = '''    if not isinstance(discovery.get("require_acceptance", True), bool):\n        raise ValueError("workspace.discovery.require_acceptance must be boolean")\n'''
    validation = validation_anchor + '''    retrieval = data["workspace"].get(\n        "retrieval",\n        {"max_selected_repositories": 3, "max_workers": 3, "deadline_seconds": 12},\n    )\n    if not isinstance(retrieval, dict):\n        raise ValueError("workspace.retrieval must be an object")\n    _positive_int(\n        retrieval.get("max_selected_repositories", 3),\n        "workspace.retrieval.max_selected_repositories",\n    )\n    _positive_int(retrieval.get("max_workers", 3), "workspace.retrieval.max_workers")\n    deadline = retrieval.get("deadline_seconds", 12)\n    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or float(deadline) <= 0:\n        raise ValueError("workspace.retrieval.deadline_seconds must be a positive number")\n'''
    if 'workspace.retrieval.deadline_seconds must be a positive number' not in text:
        if validation_anchor not in text:
            raise SystemExit('workspace validation marker not found')
        text = text.replace(validation_anchor, validation, 1)
    path.write_text(text, encoding='utf-8')


def write_impl() -> None:
    Path('ai_workflow/workspace_selector.py').write_text(SELECTOR_MODULE, encoding='utf-8')
    Path('ai_workflow/workspace_budget.py').write_text(BUDGET_MODULE, encoding='utf-8')
    patch_config()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['tests', 'impl'])
    args = parser.parse_args()
    if args.mode == 'tests':
        write_tests()
    else:
        write_impl()


if __name__ == '__main__':
    main()
