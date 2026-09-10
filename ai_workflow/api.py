from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._version import __version__
from .budget import ContextBudget, budget_for
from .classifier import classify
from .config import default_config, load_config
from .models import ContextItem, RouteDecision
from .provenance import (
    ArtifactReference,
    LocalRunStore,
    RunMetadata,
    RunStore,
    changed_files_digest,
    config_digest,
    git_head,
    index_manifest_digest,
    provider_versions_from_config,
)
from .providers import ProviderStatus, detect, execution_provider, model_tier
from .workflow_engine import WorkflowEngine


@dataclass(frozen=True)
class TaskRequest:
    """Typed input for preparing one control-plane task."""

    text: str
    root: Path
    symbol: str | None = None
    endpoint: str | None = None
    changed_files: tuple[str, ...] = ()
    artifacts: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("task text must not be blank")


@dataclass(frozen=True)
class WorkflowResult:
    """Prepared decision, evidence, execution contract and provenance."""

    task: TaskRequest
    decision: RouteDecision
    context: tuple[ContextItem, ...]
    retrieval: Mapping[str, Any]
    budget: ContextBudget
    providers: ProviderStatus
    execution_provider: str
    model_tier: str
    run: RunMetadata


class WorkflowClient:
    """Library facade over the same engine used by the CLI."""

    def __init__(
        self,
        *,
        engine: Any | None = None,
        run_store: RunStore | None = None,
        persist_runs: bool = False,
    ) -> None:
        self.engine = engine or WorkflowEngine()
        self.run_store = run_store
        self.persist_runs = bool(persist_runs)

    def _config(self, root: Path) -> dict[str, Any]:
        try:
            return load_config(root)
        except FileNotFoundError:
            return default_config()

    async def prepare(self, task: TaskRequest) -> WorkflowResult:
        root = Path(task.root).resolve()
        config = self._config(root)
        providers = detect(root, config)
        decision = classify(task.text, config)
        budget = budget_for(decision.lane, config)
        items, retrieval = await self.engine.gather_detailed_async(
            root,
            task.text,
            decision,
            budget,
            config,
            providers,
            task.symbol,
            task.endpoint,
            list(task.changed_files),
            write_telemetry=False,
        )
        workspace_state = retrieval.get("workspace_state")
        fingerprint = (
            str(workspace_state.get("fingerprint", "unknown"))
            if isinstance(workspace_state, Mapping)
            else "unknown"
        )
        run = RunMetadata.create(
            control_plane_version=__version__,
            workspace_fingerprint=fingerprint,
            git_head=git_head(root),
            changed_files_digest=changed_files_digest(task.changed_files),
            config_digest=config_digest(config),
            retrieval_policy_version=str(config.get("version", "unknown")),
            index_manifest_digest=index_manifest_digest(root),
            provider_versions=provider_versions_from_config(config),
            artifacts=task.artifacts,
        )
        if self.persist_runs:
            store = self.run_store or LocalRunStore(
                root / "ai-workspace" / "runs"
            )
            store.add(run)
        return WorkflowResult(
            task=task,
            decision=decision,
            context=tuple(items),
            retrieval=retrieval,
            budget=budget,
            providers=providers,
            execution_provider=execution_provider(
                decision.lane,
                config,
                providers,
            ),
            model_tier=model_tier(decision, config),
            run=run,
        )


async def prepare(
    task: TaskRequest,
    *,
    client: WorkflowClient | None = None,
) -> WorkflowResult:
    """Prepare a task using a supplied client or the safe default client."""

    return await (client or WorkflowClient()).prepare(task)
