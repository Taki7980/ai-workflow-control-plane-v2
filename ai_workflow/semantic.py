from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import ContextItem
from .provider_registry import resolve_project_provider, unsafe_repo_commands_enabled
from .provider_runner import run_command_provider
from .retrieval_contracts import ProviderResult, RetrievalRequest


BUILTIN_SEMANTIC_PROVIDER_ID = "builtin-local"


def configured_provider_id(config: dict) -> str:
    semantic = ((config.get("context") or {}).get("semantic") or {})
    if str(semantic.get("mode", "auto")).lower() == "off":
        return ""
    environment_provider = os.getenv(
        "AI_WORKFLOW_SEMANTIC_PROVIDER_ID", ""
    ).strip()
    if environment_provider:
        return environment_provider
    configured = str(semantic.get("provider_id") or "").strip()
    # Auto mode is useful without a second setup command: when no external
    # provider is selected, use the dependency-free local hybrid retriever.
    return configured or BUILTIN_SEMANTIC_PROVIDER_ID


def configured_command(config: dict) -> str | list[str]:
    """Return a legacy command only when unsafe compatibility is explicit."""

    semantic = ((config.get("context") or {}).get("semantic") or {})
    if (
        str(semantic.get("mode", "auto")).lower() == "off"
        or not unsafe_repo_commands_enabled()
    ):
        return ""
    environment_command = os.getenv("AI_WORKFLOW_SEMANTIC_CMD", "").strip()
    if environment_command:
        return environment_command
    configured = semantic.get("command", "")
    if isinstance(configured, list):
        return [str(part) for part in configured]
    return str(configured).strip()


def semantic_ready(config: dict) -> bool:
    return bool(configured_provider_id(config) or configured_command(config))


def _semantic_terms(text: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {
        token
        for token in re.findall(r"[A-Za-z0-9]+", expanded.lower())
        if len(token) >= 2
    }


def _trigrams(text: str) -> set[str]:
    compact = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    if len(compact) < 3:
        return {compact} if compact else set()
    return {compact[i:i + 3] for i in range(len(compact) - 2)}


def _hybrid_similarity(query: str, candidate: str) -> float:
    q_terms = _semantic_terms(query)
    c_terms = _semantic_terms(candidate)
    token_union = q_terms | c_terms
    token_score = (
        len(q_terms & c_terms) / len(token_union)
        if token_union
        else 0.0
    )
    q_grams = _trigrams(query)
    c_grams = _trigrams(candidate)
    gram_union = q_grams | c_grams
    gram_score = (
        len(q_grams & c_grams) / len(gram_union)
        if gram_union
        else 0.0
    )
    phrase_bonus = 0.25 if query.strip().lower() in candidate.lower() else 0.0
    return min(1.0, 0.7 * token_score + 0.3 * gram_score + phrase_bonus)


def _index_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _builtin_semantic_result(
    root: Path,
    query: str,
    limit: int,
) -> ProviderResult:
    root = Path(root).resolve()
    generated = root / "ai-workspace" / "generated"
    ranked: list[tuple[float, dict]] = []
    for filename in ("symbol-index.jsonl", "endpoint-index.jsonl"):
        for row in _index_rows(generated / filename):
            candidate = " ".join(
                str(row.get(key, ""))
                for key in ("symbol", "kind", "method", "path", "file")
            )
            score = _hybrid_similarity(query, candidate)
            if score > 0:
                ranked.append((score, row))

    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("file", "")),
            int(item[1].get("line", 0) or 0),
        )
    )
    items: list[ContextItem] = []
    seen: set[tuple[str, int]] = set()
    for score, row in ranked:
        if len(items) >= max(1, int(limit)):
            break
        relative = str(row.get("file") or "").strip()
        line_number = int(row.get("line", 1) or 1)
        if not relative:
            continue
        key = (relative, line_number)
        if key in seen:
            continue
        seen.add(key)
        candidate_path = root / relative
        try:
            resolved = candidate_path.resolve()
            resolved.relative_to(root)
            lines = resolved.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except (OSError, ValueError):
            continue
        start = max(0, line_number - 4)
        end = min(len(lines), line_number + 4)
        snippet = "\n".join(
            f"{index + 1}: {lines[index]}"
            for index in range(start, end)
        )
        if not snippet:
            continue
        items.append(
            ContextItem(
                "semantic",
                f"{relative}:{line_number}\n{snippet}",
                score,
                False,
                {
                    "path": relative,
                    "line": line_number,
                    "retriever": "semantic",
                    "provider": BUILTIN_SEMANTIC_PROVIDER_ID,
                },
            )
        )
    return ProviderResult("semantic", tuple(items))


def semantic_result(
    root: Path,
    query: str,
    config: dict,
    limit: int,
) -> ProviderResult:
    semantic = dict(((config.get("context") or {}).get("semantic") or {}))
    provider_id = configured_provider_id(config)
    command = configured_command(config)
    if not provider_id and not command:
        return ProviderResult(
            "semantic",
            error="semantic provider is not configured",
            error_kind="not_configured",
        )
    if provider_id == BUILTIN_SEMANTIC_PROVIDER_ID:
        return _builtin_semantic_result(root, query, limit)

    semantic["name"] = "semantic"
    if provider_id:
        semantic["provider_id"] = provider_id
        semantic.pop("command", None)
        semantic.pop("env_allowlist", None)
    else:
        semantic["command"] = command

    try:
        provider = resolve_project_provider(
            root,
            semantic,
            default_name="semantic",
        )
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


def semantic_context(
    root: Path,
    query: str,
    config: dict,
    limit: int,
) -> list[ContextItem]:
    """Backward-compatible list API over the typed provider result boundary."""

    result = semantic_result(root, query, config, limit)
    if result.error_kind == "not_configured":
        return []
    return list(result.items)
