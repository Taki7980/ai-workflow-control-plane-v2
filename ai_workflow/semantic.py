from __future__ import annotations

import os
from pathlib import Path

from .models import ContextItem
from .provider_runner import command_provider_spec, run_command_provider
from .retrieval_contracts import ProviderResult, RetrievalRequest


def configured_command(config: dict) -> str | list[str]:
    semantic = ((config.get("context") or {}).get("semantic") or {})
    if str(semantic.get("mode", "auto")).lower() == "off":
        return ""
    environment_command = os.getenv("AI_WORKFLOW_SEMANTIC_CMD", "").strip()
    if environment_command:
        return environment_command
    configured = semantic.get("command", "")
    if isinstance(configured, list):
        return [str(part) for part in configured]
    return str(configured).strip()


def semantic_ready(config: dict) -> bool:
    return bool(configured_command(config))


def semantic_result(root: Path, query: str, config: dict, limit: int) -> ProviderResult:
    command = configured_command(config)
    if not command:
        return ProviderResult("semantic", error="semantic provider is not configured", error_kind="not_configured")

    semantic = dict(((config.get("context") or {}).get("semantic") or {}))
    semantic["name"] = "semantic"
    semantic["command"] = command
    try:
        provider = command_provider_spec(semantic, default_name="semantic")
        request = RetrievalRequest(
            query=query,
            root=root,
            limit=max(1, int(limit)),
            intent="semantic",
            timeout_seconds=provider.timeout_seconds,
        )
    except (TypeError, ValueError) as exc:
        return ProviderResult(
            "semantic",
            error=f"invalid semantic provider configuration: {type(exc).__name__}",
            error_kind="configuration",
        )

    return run_command_provider(
        provider,
        request,
        source="semantic",
        metadata_defaults={"retriever": "semantic"},
    )


def semantic_context(root: Path, query: str, config: dict, limit: int) -> list[ContextItem]:
    """Backward-compatible list API over the typed provider result boundary."""

    result = semantic_result(root, query, config, limit)
    if result.error_kind == "not_configured":
        return []
    return list(result.items)
