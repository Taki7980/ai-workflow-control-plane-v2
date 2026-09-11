from __future__ import annotations

from pathlib import Path

from .models import ContextItem
from .provider_registry import resolve_project_provider, unsafe_repo_commands_enabled
from .provider_runner import run_command_provider
from .retrieval_contracts import ProviderResult, RetrievalRequest


VALID_INTENTS = {"exact", "semantic", "structural", "mixed", "all"}


def configured_retrievers(config: dict, intent: str) -> list[dict]:
    raw = ((config.get("context") or {}).get("external_retrievers") or [])
    out = []
    for item in raw:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        name = str(item.get("name", "")).strip()
        provider_id = str(item.get("provider_id") or "").strip()
        command = item.get("command", "")
        has_legacy_command = (
            bool(command)
            if isinstance(command, (list, tuple))
            else bool(str(command).strip())
        )
        configured = provider_id or (
            has_legacy_command and unsafe_repo_commands_enabled()
        )
        intents = {
            str(x).strip().lower()
            for x in (item.get("intents") or ["all"])
        }
        if not name or not configured or not intents.issubset(VALID_INTENTS):
            continue
        if "all" in intents or intent in intents:
            out.append(item)
    return out


def run_retriever_result(
    root: Path,
    query: str,
    intent: str,
    spec: dict,
    limit: int,
) -> ProviderResult:
    name = str(spec.get("name", "external")).strip() or "external"
    try:
        provider = resolve_project_provider(
            root,
            spec,
            default_name=name,
        )
        request = RetrievalRequest(
            query=query,
            root=root,
            limit=max(1, int(limit)),
            intent=intent,
            timeout_seconds=provider.timeout_seconds,
        )
    except (TypeError, ValueError) as exc:
        return ProviderResult(
            name,
            error=f"invalid provider configuration: {type(exc).__name__}",
            error_kind="configuration",
        )

    return run_command_provider(
        provider,
        request,
        source=f"external:{name}",
        metadata_defaults={"retriever": name, "plugin": True},
    )


def run_retriever(
    root: Path,
    query: str,
    intent: str,
    spec: dict,
    limit: int,
) -> list[ContextItem]:
    """Backward-compatible list API over the typed provider result boundary."""

    return list(run_retriever_result(root, query, intent, spec, limit).items)
