from __future__ import annotations

import argparse
from pathlib import Path


SCOPED_TESTS = r'''from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.context_broker import lightweight
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.workflow_engine import WorkflowEngine


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ScopedRetrievalTests(unittest.TestCase):
    def test_lightweight_reads_central_index_but_returns_repo_local_path(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            backend = workspace / "backend"
            frontend = workspace / "frontend"
            backend.mkdir()
            frontend.mkdir()
            backend_file = backend / "payments.py"
            frontend_file = frontend / "payment.ts"
            backend_file.write_text("def ProcessPayment():\n    return True\n", encoding="utf-8")
            frontend_file.write_text("export function PaymentForm() {}\n", encoding="utf-8")
            generated = workspace / "ai-workspace" / "generated"
            generated.mkdir(parents=True)
            backend_sha = _sha(backend_file)
            frontend_sha = _sha(frontend_file)
            (generated / "index-state.json").write_text(
                json.dumps({
                    "version": 2,
                    "files": {
                        "backend/payments.py": {"sha256": backend_sha},
                        "frontend/payment.ts": {"sha256": frontend_sha},
                    },
                }),
                encoding="utf-8",
            )
            (generated / "symbol-index.jsonl").write_text(
                "\n".join([
                    json.dumps({"symbol": "ProcessPayment", "file": "backend/payments.py", "line": 1, "sha256": backend_sha}),
                    json.dumps({"symbol": "PaymentForm", "file": "frontend/payment.ts", "line": 1, "sha256": frontend_sha}),
                ]) + "\n",
                encoding="utf-8",
            )
            (generated / "endpoint-index.jsonl").write_text("", encoding="utf-8")

            items = lightweight(
                backend,
                "ProcessPayment",
                "ProcessPayment",
                None,
                6,
                0.5,
                workspace_root=workspace,
                repository_path="backend",
            )

            texts = "\n".join(item.text for item in items)
            self.assertIn("ProcessPayment", texts)
            self.assertNotIn("PaymentForm", texts)
            self.assertIn('"file":"payments.py"', texts)
            self.assertNotIn('"file":"backend/payments.py"', texts)

    def test_workflow_engine_scoped_call_uses_one_repo_and_exact_slice(self):
        captured = []

        def base_gather(root, query, decision, budget, config, providers, symbol, endpoint, changed, **kwargs):
            captured.append((Path(root), budget.context_chars, tuple(changed), kwargs))
            return [ContextItem("targeted_source", "payments.py:1 ProcessPayment", 1.0)]

        config = default_config()
        providers = ProviderStatus(False, False, False, False, False)
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
        budget = ContextBudget(100, 20, 1200, {"hot_cache": 100, "lightweight": 300, "crg": 400, "source_fallback": 400})

        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            repo = workspace / "backend"
            repo.mkdir()
            engine = WorkflowEngine(base_gather=base_gather)
            items, diagnostics = engine.gather_detailed(
                repo,
                "ProcessPayment",
                decision,
                budget,
                config,
                providers,
                changed_files=["payments.py"],
                workspace_root=workspace,
                repository_path="backend",
            )

        self.assertTrue(items)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0].name, "backend")
        self.assertEqual(captured[0][1], 1200)
        self.assertEqual(captured[0][2], ("payments.py",))
        self.assertEqual(Path(captured[0][3]["workspace_root"]).name, Path(td).name)
        self.assertEqual(captured[0][3]["repository_path"], "backend")
        self.assertEqual(diagnostics["repository_path"], "backend")

    def test_unscoped_engine_preserves_legacy_base_gather_signature(self):
        calls = []

        def legacy_base(root, query, decision, budget, config, providers, symbol, endpoint, changed):
            calls.append(Path(root))
            return [ContextItem("targeted_source", "legacy.py:1 answer", 1.0)]

        config = default_config()
        providers = ProviderStatus(False, False, False, False, False)
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
        budget = ContextBudget(100, 20, 600, {"hot_cache": 50, "lightweight": 150, "crg": 200, "source_fallback": 200})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            engine = WorkflowEngine(base_gather=legacy_base)
            items, _ = engine.gather_detailed(root, "answer", decision, budget, config, providers)
        self.assertTrue(items)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
'''


WORKSPACE_TESTS = r'''from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.workspace_budget import RepositoryBudget
from ai_workflow.workspace_retrieval import gather_workspace_detailed_async
from ai_workflow.workspace_selector import RepositoryCandidate, RepositorySelection


class WorkspaceRetrievalTests(unittest.TestCase):
    def test_multi_repo_merge_preserves_provenance_and_parent_budget(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            a_root = workspace / "backend"
            b_root = workspace / "frontend"
            skipped_root = workspace / "docs"
            for root in (a_root, b_root, skipped_root):
                root.mkdir()

            a = RepositoryCandidate(a_root, "repo-a", "backend", "github.com/acme/backend", "fp-a", ("payments.py",), False)
            b = RepositoryCandidate(b_root, "repo-b", "frontend", "github.com/acme/frontend", "fp-b", (), False)
            c = RepositoryCandidate(skipped_root, "repo-c", "docs", "github.com/acme/docs", "fp-c", (), False)
            selections = [
                RepositorySelection(a, 20.0, 1, True, ("changed_file",)),
                RepositorySelection(b, 10.0, 2, True, ("identity_match",)),
                RepositorySelection(c, 0.0, 3, False, ("no_relevant_signal",)),
            ]
            parent = ContextBudget(300, 60, 1000, {"hot_cache": 100, "lightweight": 300, "crg": 400, "source_fallback": 200})
            budgets = [
                RepositoryBudget("repo-a", 1, 0.6, ContextBudget(180, 0, 600, {"hot_cache": 60, "lightweight": 180, "crg": 240, "source_fallback": 120})),
                RepositoryBudget("repo-b", 2, 0.4, ContextBudget(120, 0, 400, {"hot_cache": 40, "lightweight": 120, "crg": 160, "source_fallback": 80})),
            ]
            config = default_config()
            providers = ProviderStatus(False, False, False, False, False)
            decision = RouteDecision(Lane.FULL, Risk.MEDIUM, ["test"], True, 0.9)

            async def fake_gather(root, query, decision, budget, config, providers, symbol=None, endpoint=None, changed_files=None, **kwargs):
                if Path(root).name == "backend":
                    await asyncio.sleep(0.02)
                item = ContextItem("targeted_source", "shared evidence", 1.0, False, {"file": "x.py"}, {"workspace_root": "/must/not/leak"})
                return [item], {"retrieval_intent": "mixed", "evidence_state": "sufficient", "sufficiency": {"sufficient": True, "score": 1.0}, "fallbacks": [], "orchestration": {"complexity_score": 1}}

            with patch("ai_workflow.workspace_retrieval.build_repository_candidates", return_value=[a, b, c]), \
                 patch("ai_workflow.workspace_retrieval.select_repositories", return_value=selections), \
                 patch("ai_workflow.workspace_retrieval.allocate_repository_budgets", return_value=budgets), \
                 patch("ai_workflow.workspace_retrieval.aggregate_workspace_fingerprint", return_value={"fingerprint": "workspace-fp"}), \
                 patch("ai_workflow.workspace_retrieval.gather_detailed_async", new=fake_gather):
                result = asyncio.run(gather_workspace_detailed_async(workspace, "fix payments", decision, parent, config, providers))

            self.assertEqual([item.metadata["repository_id"] for item in result.items], ["repo-a", "repo-b"])
            self.assertEqual(len(result.items), 2, "same text from different repos must not dedupe away provenance")
            for item in result.items:
                self.assertIn("repository_path", item.metadata)
                self.assertIn("repository_fingerprint", item.metadata)
                self.assertEqual(item.metadata["repository_id"], item.provenance["repository_id"])
                self.assertNotIn("workspace_root", item.provenance)
                self.assertNotIn("root", item.provenance)
            self.assertEqual(result.diagnostics["workspace_fingerprint"], "workspace-fp")
            self.assertEqual(result.diagnostics["repositories_searched"], ["repo-a", "repo-b"])
            self.assertEqual(result.diagnostics["repositories_skipped"], ["repo-c"])
            self.assertLessEqual(result.diagnostics["budget"]["used_context_chars"], 1000)
            self.assertEqual(result.diagnostics["budget"]["allocated_context_chars"], 1000)
            self.assertEqual(result.diagnostics["primary_retrieval"]["retrieval_intent"], "mixed")

    def test_global_deadline_marks_slow_repository_without_retry(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            repo = workspace / "backend"
            repo.mkdir()
            candidate = RepositoryCandidate(repo, "repo-a", "backend", None, "fp", (), False)
            selection = RepositorySelection(candidate, 10.0, 1, True, ("identity_match",))
            parent = ContextBudget(100, 20, 300, {"hot_cache": 30, "lightweight": 90, "crg": 120, "source_fallback": 60})
            repo_budget = RepositoryBudget("repo-a", 1, 1.0, parent)
            config = default_config()
            config["workspace"]["retrieval"]["deadline_seconds"] = 0.01
            providers = ProviderStatus(False, False, False, False, False)
            decision = RouteDecision(Lane.ANSWER, Risk.LOW, ["test"], False, 0.9)
            calls = 0

            async def slow(*args, **kwargs):
                nonlocal calls
                calls += 1
                await asyncio.sleep(0.05)
                return [], {}

            with patch("ai_workflow.workspace_retrieval.build_repository_candidates", return_value=[candidate]), \
                 patch("ai_workflow.workspace_retrieval.select_repositories", return_value=[selection]), \
                 patch("ai_workflow.workspace_retrieval.allocate_repository_budgets", return_value=[repo_budget]), \
                 patch("ai_workflow.workspace_retrieval.aggregate_workspace_fingerprint", return_value={"fingerprint": "fp"}), \
                 patch("ai_workflow.workspace_retrieval.gather_detailed_async", new=slow):
                result = asyncio.run(gather_workspace_detailed_async(workspace, "task", decision, parent, config, providers))

            self.assertEqual(calls, 1)
            self.assertTrue(result.diagnostics["scheduler"]["deadline_exceeded"])
            self.assertEqual(result.diagnostics["repository_results"]["repo-a"]["status"], "deadline")


if __name__ == "__main__":
    unittest.main()
'''


WORKSPACE_RETRIEVAL = r'''from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adaptive_broker import gather_detailed_async
from .budget import ContextBudget, truncate
from .models import ContextItem, RouteDecision
from .providers import ProviderStatus
from .workspace_budget import RepositoryBudget, allocate_repository_budgets
from .workspace_selector import (
    RepositoryCandidate,
    RepositorySelection,
    build_repository_candidates,
    select_repositories,
)
from .workspace_state import aggregate_workspace_fingerprint


@dataclass(frozen=True)
class WorkspaceRetrievalResult:
    items: tuple[ContextItem, ...]
    diagnostics: dict[str, Any]


def _portable_changed_path(candidate: RepositoryCandidate, local_path: str) -> str:
    local = str(local_path).replace("\\", "/").lstrip("/")
    if candidate.repository_path == ".":
        return local
    return f"{candidate.repository_path.rstrip('/')}/{local}" if local else candidate.repository_path


def _portable_item(item: ContextItem, candidate: RepositoryCandidate) -> ContextItem:
    metadata = dict(item.metadata)
    provenance = dict(item.provenance)
    for container in (metadata, provenance):
        container.pop("root", None)
        container.pop("workspace_root", None)
        container["repository_id"] = candidate.repository_id
        container["repository_path"] = candidate.repository_path
        container["repository_fingerprint"] = candidate.fingerprint
    return ContextItem(item.source, item.text, item.score, item.stale, metadata, provenance)


def _source_path(item: ContextItem) -> str:
    for container in (item.metadata, item.provenance):
        for key in ("file", "path"):
            value = container.get(key)
            if value:
                return str(value).replace("\\", "/").lstrip("./")
    return ""


def _cap_workspace_items(entries: list[tuple[Any, ...]], context_chars: int) -> tuple[ContextItem, ...]:
    out: list[ContextItem] = []
    seen: set[tuple[str, str]] = set()
    used = 0
    for *_, item in sorted(entries):
        repo_id = str(item.metadata.get("repository_id", ""))
        key = (repo_id, item.dedupe_key)
        if key in seen or used >= context_chars:
            continue
        seen.add(key)
        text, cut = truncate(item.text, context_chars - used)
        if not text:
            continue
        metadata = dict(item.metadata)
        if cut:
            metadata["truncated"] = True
        out.append(ContextItem(item.source, text, item.score, item.stale, metadata, dict(item.provenance)))
        used += len(text)
    return tuple(out)


async def gather_workspace_detailed_async(
    workspace_root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: list[str] | None = None,
    *,
    write_telemetry: bool = False,
) -> WorkspaceRetrievalResult:
    workspace_root = Path(workspace_root).resolve()
    candidates = build_repository_candidates(workspace_root, config, changed_files)
    retrieval_cfg = ((config.get("workspace") or {}).get("retrieval") or {})
    selector_cfg = ((config.get("context") or {}).get("selector") or {})
    selections = select_repositories(
        workspace_root,
        candidates,
        query,
        symbol=symbol,
        endpoint=endpoint,
        max_selected=max(1, int(retrieval_cfg.get("max_selected_repositories", 3))),
        max_index_candidates=max(1, int(selector_cfg.get("max_selector_candidates", 200))),
    )
    selected = sorted((row for row in selections if row.selected), key=lambda row: (row.rank, row.candidate.repository_id))
    repo_budgets = allocate_repository_budgets(budget, selections)
    budget_by_id = {row.repository_id: row for row in repo_budgets}
    max_workers = max(1, int(retrieval_cfg.get("max_workers", 3)))
    deadline_seconds = max(0.01, float(retrieval_cfg.get("deadline_seconds", 12)))
    deadline_at = time.monotonic() + deadline_seconds
    semaphore = asyncio.Semaphore(max_workers)

    async def run_one(selection: RepositorySelection):
        candidate = selection.candidate
        allocation = budget_by_id.get(candidate.repository_id)
        if allocation is None:
            return selection, None, (), {}, "budget_unavailable", 0.0
        started = time.perf_counter()
        async with semaphore:
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                return selection, allocation, (), {}, "deadline", (time.perf_counter() - started) * 1000
            try:
                items, diagnostics = await asyncio.wait_for(
                    gather_detailed_async(
                        candidate.root,
                        query,
                        decision,
                        allocation.context,
                        config,
                        providers,
                        symbol,
                        endpoint,
                        list(candidate.changed_files),
                        write_telemetry=write_telemetry,
                        workspace_root=workspace_root,
                        repository_path=candidate.repository_path,
                    ),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                return selection, allocation, (), {}, "deadline", (time.perf_counter() - started) * 1000
            except Exception as exc:
                return selection, allocation, (), {"error": f"{type(exc).__name__}: {exc}"}, "error", (time.perf_counter() - started) * 1000
        portable = tuple(_portable_item(item, candidate) for item in items)
        return selection, allocation, portable, diagnostics, "ok", (time.perf_counter() - started) * 1000

    results = await asyncio.gather(*(run_one(row) for row in selected)) if selected else []
    entries: list[tuple[Any, ...]] = []
    repository_results: dict[str, dict[str, Any]] = {}
    primary_retrieval: dict[str, Any] = {}
    allocated_context_chars = 0
    used_context_chars = 0
    deadline_exceeded = False
    searched: list[str] = []

    for selection, allocation, items, diagnostics, status, latency_ms in sorted(
        results,
        key=lambda row: (row[0].rank, row[0].candidate.repository_id),
    ):
        candidate = selection.candidate
        searched.append(candidate.repository_id)
        allocated = allocation.context.context_chars if allocation else 0
        allocated_context_chars += allocated
        used = sum(len(item.text) for item in items)
        used_context_chars += used
        if status == "deadline":
            deadline_exceeded = True
        if not primary_retrieval and status == "ok":
            primary_retrieval = diagnostics
        repository_results[candidate.repository_id] = {
            "status": status,
            "repository_path": candidate.repository_path,
            "rank": selection.rank,
            "selection_score": selection.score,
            "selection_reasons": list(selection.reasons),
            "changed_files": list(candidate.changed_files),
            "allocated_context_chars": allocated,
            "used_context_chars": used,
            "latency_ms": round(latency_ms, 2),
            "error": diagnostics.get("error") if status == "error" else None,
        }
        changed = set(candidate.changed_files)
        for local_rank, item in enumerate(items):
            source_path = _source_path(item)
            changed_boost = 1 if source_path and source_path in changed else 0
            entries.append((
                local_rank,
                -float(selection.score),
                -changed_boost,
                candidate.repository_id,
                item.source,
                source_path,
                item.dedupe_key,
                item,
            ))

    final_items = _cap_workspace_items(entries, budget.context_chars)
    final_used = sum(len(item.text) for item in final_items)
    aggregate = aggregate_workspace_fingerprint(workspace_root, config)
    selected_ids = {row.candidate.repository_id for row in selected}
    skipped = [
        row.candidate.repository_id
        for row in sorted(selections, key=lambda row: (row.rank, row.candidate.repository_id))
        if row.candidate.repository_id not in selected_ids
    ]
    changed_detected = sorted({
        _portable_changed_path(row.candidate, path)
        for row in selections
        for path in row.candidate.changed_files
    })
    diagnostics: dict[str, Any] = {
        "workspace_fingerprint": aggregate.get("fingerprint", ""),
        "repository_count": len(candidates),
        "repositories_searched": searched,
        "repositories_skipped": skipped,
        "changed_files_detected": changed_detected,
        "selection": [
            {
                "repository_id": row.candidate.repository_id,
                "repository_path": row.candidate.repository_path,
                "rank": row.rank,
                "score": row.score,
                "selected": row.selected,
                "reasons": list(row.reasons),
            }
            for row in sorted(selections, key=lambda row: (row.rank, row.candidate.repository_id))
        ],
        "repository_results": repository_results,
        "budget": {
            "parent_context_chars": budget.context_chars,
            "allocated_context_chars": allocated_context_chars,
            "used_context_chars": final_used,
            "raw_repository_used_context_chars": used_context_chars,
        },
        "scheduler": {
            "max_workers": max_workers,
            "deadline_seconds": deadline_seconds,
            "deadline_exceeded": deadline_exceeded,
        },
        "primary_retrieval": primary_retrieval,
    }
    return WorkspaceRetrievalResult(final_items, diagnostics)


def gather_workspace_detailed(*args, **kwargs) -> WorkspaceRetrievalResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(gather_workspace_detailed_async(*args, **kwargs))
    raise RuntimeError("gather_workspace_detailed() cannot run inside an event loop; use gather_workspace_detailed_async()")
'''


CONTEXT_HELPERS = r'''def _accepted_child_repository_paths(workspace_root: Path, config: dict) -> tuple[str, ...]:
    from .workspace import workspace_roots

    root = Path(workspace_root).resolve()
    paths: list[str] = []
    for candidate in workspace_roots(root, config):
        candidate = Path(candidate).resolve()
        if candidate == root:
            continue
        try:
            rel = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel and rel != ".":
            paths.append(rel)
    return tuple(sorted(set(paths)))


def _scope_index_row(
    row: dict,
    repository_path: str,
    child_repository_paths: tuple[str, ...] = (),
) -> tuple[dict, str] | None:
    original = str(row.get("file", "")).replace("\\", "/").lstrip("./")
    if not original:
        return dict(row), ""
    repo = str(repository_path or ".").replace("\\", "/").strip("/") or "."
    if repo == ".":
        if any(original.startswith(path.rstrip("/") + "/") for path in child_repository_paths):
            return None
        local = original
    elif repo.startswith("legacy:"):
        return None
    else:
        prefix = repo.rstrip("/") + "/"
        if not original.startswith(prefix):
            return None
        local = original[len(prefix):]
        if not local:
            return None
    scoped = dict(row)
    scoped["file"] = local
    return scoped, original


def _state_key(repository_path: str, local_path: str) -> str:
    local = str(local_path).replace("\\", "/").lstrip("./")
    repo = str(repository_path or ".").replace("\\", "/").strip("/") or "."
    if repo == "." or repo.startswith("legacy:"):
        return local
    return f"{repo.rstrip('/')}/{local}" if local else repo


def _scoped_row_fresh(root: Path, row: dict, original_file: str, state: dict) -> bool:
    local = str(row.get("file", ""))
    if not local:
        return True
    path = Path(root) / local
    expected = ((state.get("files") or {}).get(original_file) or {}).get("sha256")
    if not expected or row.get("sha256") != expected or not path.is_file():
        return False
    try:
        return sha256(path) == expected
    except OSError:
        return False


def _scoped_index_file_count(state: dict, repository_path: str, child_repository_paths: tuple[str, ...]) -> int:
    count = 0
    for file in (state.get("files") or {}):
        scoped = _scope_index_row({"file": file}, repository_path, child_repository_paths)
        if scoped is not None:
            count += 1
    return count


'''


FIND_TESTS = r'''def find_tests_for_changed(
    root: Path,
    changed_files: list[str],
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> list[ContextItem]:
    index_root = Path(workspace_root).resolve() if workspace_root is not None else Path(root).resolve()
    state = load_state(index_root)
    known = state.get("files", {})
    results = []
    seen = set()
    for changed in changed_files:
        p = Path(changed)
        stem = p.stem
        candidates = [
            p.with_name(f"test_{p.name}"), p.with_name(f"{stem}_test{p.suffix}"),
            Path("tests") / f"test_{p.name}", Path("test") / f"{stem}_test{p.suffix}",
            Path("__tests__") / f"{stem}.test{p.suffix}",
        ]
        for cand in candidates:
            rel = cand.as_posix()
            key = _state_key(repository_path, rel)
            if (key in known or (Path(root) / rel).is_file()) and rel not in seen:
                seen.add(rel)
                results.append(ContextItem("test_resolver", rel, 7.0, False, {"changed_file": changed, "path": rel}))
    return results


'''


LIGHTWEIGHT = r'''def lightweight(
    root: Path,
    query: str,
    symbol: str | None,
    endpoint: str | None,
    limit: int,
    min_conf: float,
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
    child_repository_paths: tuple[str, ...] = (),
) -> list[ContextItem]:
    index_root = Path(workspace_root).resolve() if workspace_root is not None else Path(root).resolve()
    state = load_state(index_root)
    sym = _jsonl(index_root / "ai-workspace/generated/symbol-index.jsonl")
    ep = _jsonl(index_root / "ai-workspace/generated/endpoint-index.jsonl")
    target = symbol or endpoint or query
    scored: list[ContextItem] = []
    for raw in sym:
        mapped = _scope_index_row(raw, repository_path, child_repository_paths)
        if mapped is None:
            continue
        r, original = mapped
        if not _scoped_row_fresh(root, r, original, state):
            continue
        s = 10 if symbol and r.get("symbol", "").lower() == symbol.lower() else _semantic_overlap_score(target, f"{r.get('symbol','')} {r.get('file','')}")
        if s:
            scored.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s)))
    for raw in ep:
        mapped = _scope_index_row(raw, repository_path, child_repository_paths)
        if mapped is None:
            continue
        r, original = mapped
        if not _scoped_row_fresh(root, r, original, state):
            continue
        s = 10 if endpoint and endpoint.lower() in r.get("path", "").lower() else _semantic_overlap_score(target, f"{r.get('method','')} {r.get('path','')} {r.get('file','')}")
        if s:
            scored.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s)))
    scored = sorted(scored, key=lambda x: (-x.score, x.text))
    scored = _diversify_lightweight_cutoff(scored, limit)
    scored.extend(_domain_hints(index_root, query))
    scored.extend(_research_hits(index_root, query, limit))
    for m in search_memory(index_root, query, limit, min_conf):
        scored.append(ContextItem("durable_memory", m.get("summary", ""), float(m.get("confidence", 0)), False, {"id": m.get("id")}))
    return scored[:limit]


'''


GATHER = r'''def gather(
    root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: list[str] | None = None,
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> list[ContextItem]:
    root = Path(root).resolve()
    index_root = Path(workspace_root).resolve() if workspace_root is not None else root
    child_paths = _accepted_child_repository_paths(index_root, config) if repository_path == "." else ()
    limit = int(config["context"].get("max_results_per_source", 6))
    items: list[ContextItem] = []
    seen_keys: set[str] = set()

    crg_cfg = config["context"]["crg"]
    index_state = load_state(index_root)
    indexed_files = _scoped_index_file_count(index_state, repository_path, child_paths)
    min_files = int(crg_cfg.get("min_source_files", 250))
    changed_threshold = int(crg_cfg.get("changed_files_threshold", 3))
    broad_change = len(changed_files or []) >= changed_threshold
    large_full = decision.lane == Lane.FULL and indexed_files >= min_files
    wants_crg = providers.code_review_graph and crg_cfg.get("mode", "auto") != "off" and (
        decision.structural_context or broad_change or large_full
    )

    if changed_files:
        test_items = find_tests_for_changed(
            root,
            changed_files,
            workspace_root=index_root,
            repository_path=repository_path,
        )
        items += _cap_items(test_items, 600, seen_keys)
    hot = hot_cache(index_root, query, limit)
    items += _cap_items(hot, budget.source_chars.get("hot_cache", 1000), seen_keys, query=query)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_light = executor.submit(
            lightweight,
            root,
            query,
            symbol,
            endpoint,
            limit,
            float(config["memory"].get("minimum_confidence", 0.55)),
            workspace_root=index_root,
            repository_path=repository_path,
            child_repository_paths=child_paths,
        )
        f_crg = executor.submit(crg_context, root, query, symbol, changed_files, limit) if wants_crg else None

        remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
        light_budget = budget.source_chars.get("lightweight", 2000)
        light = f_light.result()
        items += _cap_items(light, min(remaining, light_budget), seen_keys, query=query)

        crg_items = f_crg.result() if f_crg else []
        if wants_crg and crg_items:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            crg_budget = min(remaining, budget.source_chars.get("crg", 3000))
            items += _cap_items(crg_items, crg_budget, seen_keys, query=query)

        code_sources = {"lightweight_index", "domain_manifest", "code_review_graph"}
        has_code_evidence = any(item.source in code_sources and _score(query, item.text) > 0 for item in items)
        needs_structural_fallback = decision.structural_context and not crg_items
        needs_mutation_fallback = decision.lane != Lane.ANSWER and not has_code_evidence
        if not items or needs_structural_fallback or needs_mutation_fallback:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            if remaining > 80:
                source_items = targeted_source(
                    root,
                    query,
                    int(config["context"]["targeted_search"].get("max_matches", 12)),
                )
                items += _cap_items(source_items, remaining, seen_keys, query=query)

    final_items: list[ContextItem] = []
    used_chars = 0
    final_seen: set[str] = set()
    for item in items:
        if used_chars >= budget.context_chars:
            break
        k = item.dedupe_key
        if k in final_seen:
            continue
        final_seen.add(k)
        text, cut = truncate(item.text, budget.context_chars - used_chars)
        if text:
            meta = dict(item.metadata)
            if cut:
                meta["truncated"] = True
            final_items.append(ContextItem(item.source, text, item.score, item.stale, meta, dict(item.provenance)))
            used_chars += len(text)
    return final_items
'''


def _replace_block(text: str, start: str, end: str, replacement: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[:i] + replacement + text[j:]


def write_tests() -> None:
    Path("tests/test_scoped_retrieval.py").write_text(SCOPED_TESTS, encoding="utf-8")
    Path("tests/test_workspace_retrieval.py").write_text(WORKSPACE_TESTS, encoding="utf-8")


def apply_context_broker() -> None:
    path = Path("ai_workflow/context_broker.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace("from .indexer import load_state, row_fresh, sha256", "from .indexer import load_state, sha256")
    if "def _accepted_child_repository_paths(" not in text:
        marker = "def find_tests_for_changed("
        text = text[:text.index(marker)] + CONTEXT_HELPERS + text[text.index(marker):]
    text = _replace_block(text, "def find_tests_for_changed(", "def _cap_items(", FIND_TESTS)
    text = _replace_block(text, "def lightweight(", "def _run_crg(", LIGHTWEIGHT)
    text = text[:text.index("def gather(")] + GATHER + "\n"
    text = text.replace(
        "out.append(ContextItem(item.source, text, item.score, item.stale, meta))",
        "out.append(ContextItem(item.source, text, item.score, item.stale, meta, dict(item.provenance)))",
    )
    path.write_text(text, encoding="utf-8")


def apply_workflow_engine() -> None:
    path = Path("ai_workflow/workflow_engine.py")
    text = path.read_text(encoding="utf-8")
    text = text.replace("from .workspace import workspace_roots\n", "")
    text = text.replace("from .workspace_state import workspace_fingerprint", "from .workspace_state import repository_fingerprint")
    old_sig = "        *,\n        write_telemetry: bool = False,\n    ) -> tuple[list[ContextItem], dict]:"
    new_sig = "        *,\n        write_telemetry: bool = False,\n        workspace_root: Path | None = None,\n        repository_path: str = \".\",\n    ) -> tuple[list[ContextItem], dict]:"
    if old_sig not in text:
        raise SystemExit("workflow engine signature marker missing")
    text = text.replace(old_sig, new_sig, 1)
    start = text.index("        roots = workspace_roots(root, config)")
    end = text.index("        base_outcomes = await scheduler.run", start)
    base = '''        roots = [Path(root).resolve()]\n        scoped_workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None\n        trace.providers_attempted.append("base")\n\n        def _base_call():\n            if scoped_workspace_root is None and repository_path == ".":\n                return self.base_gather(\n                    root, query, decision, budget, config, providers, symbol, endpoint, changed\n                )\n            return self.base_gather(\n                root, query, decision, budget, config, providers, symbol, endpoint, changed,\n                workspace_root=scoped_workspace_root or Path(root).resolve(),\n                repository_path=repository_path,\n            )\n\n        selected_roots = roots\n        base_calls = [ScheduledCall("base", _base_call)]\n\n'''
    text = text[:start] + base + text[end:]
    text = text.replace("        snapshot = workspace_fingerprint(root, changed)", "        snapshot = repository_fingerprint(root, repository_path, changed_files=changed)")
    text = text.replace(
        '            "workspace_roots": [str(path) for path in roots],\n            "workspace_state": snapshot,',
        '            "workspace_roots": [str(path) for path in roots],\n            "repository_path": repository_path,\n            "workspace_state": snapshot,',
    )
    text = text.replace(
        "            diagnostics[\"trace\"] = write_trace(root, trace)",
        "            diagnostics[\"trace\"] = write_trace(scoped_workspace_root or root, trace)",
    )
    path.write_text(text, encoding="utf-8")


def apply_adaptive_broker() -> None:
    path = Path("ai_workflow/adaptive_broker.py")
    text = path.read_text(encoding="utf-8")
    marker = "    *,\n    write_telemetry: bool = False,\n) -> tuple[list[ContextItem], dict]:"
    replacement = "    *,\n    write_telemetry: bool = False,\n    workspace_root: Path | None = None,\n    repository_path: str = \".\",\n) -> tuple[list[ContextItem], dict]:"
    if text.count(marker) < 2:
        raise SystemExit("adaptive broker signature markers missing")
    text = text.replace(marker, replacement, 2)
    call = "        write_telemetry=write_telemetry,\n    )"
    forwarded = "        write_telemetry=write_telemetry,\n        workspace_root=workspace_root,\n        repository_path=repository_path,\n    )"
    if text.count(call) < 2:
        raise SystemExit("adaptive broker call markers missing")
    text = text.replace(call, forwarded, 2)
    path.write_text(text, encoding="utf-8")


def apply_impl() -> None:
    apply_context_broker()
    apply_workflow_engine()
    apply_adaptive_broker()
    Path("ai_workflow/workspace_retrieval.py").write_text(WORKSPACE_RETRIEVAL, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("tests", "impl"))
    args = parser.parse_args()
    if args.mode == "tests":
        write_tests()
    else:
        apply_impl()


if __name__ == "__main__":
    main()
