from __future__ import annotations

from pathlib import Path

from .budget import ContextBudget
from .context_broker import gather as gather_base
from .models import ContextItem, RouteDecision
from .providers import ProviderStatus
from .retriever_plugins import run_retriever_result
from .semantic import semantic_result
from .workflow_engine import WorkflowEngine


def _engine() -> WorkflowEngine:
    # Dependency injection preserves the historical monkeypatch/test seams on
    # this module while moving sequencing into WorkflowEngine.
    return WorkflowEngine(
        base_gather=gather_base,
        semantic_provider=semantic_result,
        external_provider=run_retriever_result,
    )


async def gather_detailed_async(
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
    write_telemetry: bool = False,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> tuple[list[ContextItem], dict]:
    return await _engine().gather_detailed_async(
        root,
        query,
        decision,
        budget,
        config,
        providers,
        symbol,
        endpoint,
        changed_files,
        write_telemetry=write_telemetry,
        workspace_root=workspace_root,
        repository_path=repository_path,
    )


def gather_detailed(
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
    write_telemetry: bool = False,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> tuple[list[ContextItem], dict]:
    return _engine().gather_detailed(
        root,
        query,
        decision,
        budget,
        config,
        providers,
        symbol,
        endpoint,
        changed_files,
        write_telemetry=write_telemetry,
        workspace_root=workspace_root,
        repository_path=repository_path,
    )


def gather(
    root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: list[str] | None = None,
) -> list[ContextItem]:
    items, _ = gather_detailed(root, query, decision, budget, config, providers, symbol, endpoint, changed_files)
    return items
