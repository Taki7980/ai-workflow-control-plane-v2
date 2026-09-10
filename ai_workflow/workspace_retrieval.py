from __future__ import annotations

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
                items, repo_diagnostics = await asyncio.wait_for(
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
        return selection, allocation, portable, repo_diagnostics, "ok", (time.perf_counter() - started) * 1000

    results = await asyncio.gather(*(run_one(row) for row in selected)) if selected else []
    entries: list[tuple[Any, ...]] = []
    repository_results: dict[str, dict[str, Any]] = {}
    primary_retrieval: dict[str, Any] = {}
    allocated_context_chars = 0
    used_context_chars = 0
    deadline_exceeded = False
    searched: list[str] = []

    for selection, allocation, items, repo_diagnostics, status, latency_ms in sorted(
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
            primary_retrieval = repo_diagnostics
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
            "error": repo_diagnostics.get("error") if status == "error" else None,
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
