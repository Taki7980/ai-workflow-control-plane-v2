from __future__ import annotations

import time
from pathlib import Path

from .budget import ContextBudget, truncate
from .context_broker import gather as gather_base
from .context_selection import select_context
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, reciprocal_rank_fusion, tokenize
from .models import ContextItem, Lane, RouteDecision
from .orchestration import build_orchestration_contract
from .providers import ProviderStatus
from .retrieval_policy import classify_retrieval_intent, evaluate_sufficiency
from .retriever_plugins import configured_retrievers, run_retriever_result
from .semantic import semantic_result
from .telemetry import RetrievalTrace, trace_enabled, write_trace
from .workspace import workspace_roots
from .workspace_state import workspace_fingerprint


def _provenance(item: ContextItem, workspace_root: Path | None = None) -> ContextItem:
    metadata = dict(item.metadata)
    provenance = dict(item.provenance)
    provenance.setdefault("retriever", item.source)
    provenance.setdefault("fresh", not item.stale)
    if workspace_root is not None:
        provenance.setdefault("workspace_root", str(workspace_root))
    if item.source in {"lightweight_index", "targeted_source", "code_review_graph", "semantic", "test_resolver"} or item.source.startswith("external:"):
        provenance.setdefault("trust", "untrusted_repository_content")
    elif item.source in {"durable_memory", "hot_cache", "research_cache"}:
        provenance.setdefault("trust", "generated_or_cached_context")
    else:
        provenance.setdefault("trust", "context_data")
    for key in ("path", "file", "line", "start_line", "end_line", "sha256"):
        if key in metadata and key not in provenance:
            provenance[key] = metadata[key]
    return ContextItem(item.source, item.text, item.score, item.stale, metadata, provenance)


def _hybrid_rank(query: str, base: list[ContextItem], specialist: list[ContextItem], limit: int) -> list[ContextItem]:
    candidates = [_provenance(item) for item in [*base, *specialist]]
    if not candidates:
        return []
    lexical_scorer = BM25Scorer()
    lexical_scorer.fit([item.text for item in candidates], candidates)
    lexical_rank = [item for _, item in lexical_scorer.rank(query)]
    specialist_rank = sorted(specialist, key=lambda item: -item.score)
    source_rank = sorted(candidates, key=lambda item: -item.score)
    fused = reciprocal_rank_fusion([source_rank, lexical_rank, specialist_rank], key=lambda item: item.dedupe_key)
    fused_items = [item for _, item in fused]
    fused_scores = [score for score, _ in fused]
    if len(fused_items) <= 1:
        return fused_items[:limit]
    scorer = BM25Scorer()
    scorer.fit([item.text for item in fused_items], fused_items)
    return maximal_marginal_relevance(
        tokenize(query), scorer.docs, fused_scores, lambda_param=0.75,
        max_items=min(limit, len(fused_items)),
    )


def _hard_cap(items: list[ContextItem], chars: int) -> list[ContextItem]:
    out: list[ContextItem] = []
    seen: set[str] = set()
    used = 0
    for item in items:
        if used >= chars or item.dedupe_key in seen:
            continue
        seen.add(item.dedupe_key)
        text, cut = truncate(item.text, chars - used)
        if not text:
            continue
        metadata = dict(item.metadata)
        if cut:
            metadata["truncated"] = True
        out.append(ContextItem(item.source, text, item.score, item.stale, metadata, dict(item.provenance)))
        used += len(text)
    return out


def _adaptive_char_limit(budget: ContextBudget, score: float, config: dict) -> int:
    cfg = ((config.get("context") or {}).get("adaptive_budget") or {})
    if not cfg.get("enabled", True):
        return budget.context_chars
    high = float(cfg.get("high_sufficiency_fraction", 0.45))
    medium = float(cfg.get("medium_sufficiency_fraction", 0.7))
    minimum = int(cfg.get("minimum_chars", 900))
    fraction = high if score >= 0.86 else medium if score >= 0.72 else 1.0
    return min(budget.context_chars, max(minimum, int(budget.context_chars * fraction)))


def _base_across_workspace(
    root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None,
    endpoint: str | None,
    changed_files: list[str],
    trace: RetrievalTrace,
) -> list[ContextItem]:
    roots = workspace_roots(root, config)
    max_roots = max(1, int(((config.get("workspace") or {}).get("max_roots", 4))))
    items: list[ContextItem] = []
    for index, candidate_root in enumerate(roots[:max_roots]):
        label = "base" if index == 0 else f"workspace:{candidate_root.name}"
        trace.providers_attempted.append(label)
        start = time.perf_counter()
        candidate_changed = changed_files if index == 0 else []
        gathered = gather_base(candidate_root, query, decision, budget, config, providers, symbol, endpoint, candidate_changed)
        trace.stage_latency_ms[label] = round((time.perf_counter() - start) * 1000, 2)
        trace.candidates[label] = len(gathered)
        items.extend(_provenance(item, candidate_root) for item in gathered)
    return items


def _evidence_state(decision: RouteDecision, sufficient: bool) -> str:
    if sufficient:
        return "sufficient"
    if decision.lane == Lane.ANSWER:
        return "abstain"
    return "requires_exploration"


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
) -> tuple[list[ContextItem], dict]:
    changed = changed_files or []
    plan = classify_retrieval_intent(query, decision, symbol=symbol, endpoint=endpoint)
    trace = RetrievalTrace(query, decision.lane.value, decision.risk.value, plan.intent.value, budget_chars=budget.context_chars)
    base_items = _base_across_workspace(root, query, decision, budget, config, providers, symbol, endpoint, changed, trace)

    threshold = float((((config.get("context") or {}).get("sufficiency") or {}).get("threshold", 0.72)))
    suff = evaluate_sufficiency(query, base_items, structural_required=plan.use_structural, threshold=threshold)
    specialist_items: list[ContextItem] = []
    provider_errors: dict[str, dict] = {}

    should_semantic = plan.use_semantic and not suff.sufficient
    if should_semantic and providers.semantic:
        trace.providers_attempted.append("semantic")
        result = semantic_result(root, query, config, int(config["context"].get("max_results_per_source", 6)))
        trace.stage_latency_ms["semantic"] = round(result.latency_ms, 2)
        trace.candidates["semantic"] = len(result.items)
        if result.error:
            provider_errors["semantic"] = result.error_dict() or {"kind": "provider_error", "message": result.error}
            trace.fallbacks.append(f"semantic provider failed: {result.error_kind or 'provider_error'}")
        specialist_items.extend(_provenance(item, root) for item in result.items)
    elif plan.use_semantic:
        trace.providers_skipped["semantic"] = "provider not configured" if not providers.semantic else "base evidence sufficient"

    if not suff.sufficient:
        for spec in configured_retrievers(config, plan.intent.value):
            name = str(spec.get("name", "external"))
            label = f"external:{name}"
            trace.providers_attempted.append(label)
            result = run_retriever_result(root, query, plan.intent.value, spec, int(config["context"].get("max_results_per_source", 6)))
            trace.stage_latency_ms[label] = round(result.latency_ms, 2)
            trace.candidates[label] = len(result.items)
            if result.error:
                provider_errors[label] = result.error_dict() or {"kind": "provider_error", "message": result.error}
                trace.fallbacks.append(f"{label} failed: {result.error_kind or 'provider_error'}")
            specialist_items.extend(_provenance(item, root) for item in result.items)

    limit = int(config["context"].get("max_results_per_source", 6)) * 3
    candidates = _hybrid_rank(query, base_items, specialist_items, limit) if specialist_items else base_items
    suff = evaluate_sufficiency(query, candidates, structural_required=plan.use_structural, threshold=threshold)
    adaptive_chars = _adaptive_char_limit(budget, suff.score, config)

    selector_cfg = ((config.get("context") or {}).get("selector") or {})
    if selector_cfg.get("enabled", True):
        mandatory_sources = (
            ("code_review_graph",)
            if plan.use_structural and selector_cfg.get("mandatory_structural_evidence", True)
            and any(item.source == "code_review_graph" for item in candidates)
            else ()
        )
        selected, selector = select_context(
            query, candidates, adaptive_chars, config,
            mandatory_sources=mandatory_sources,
        )
        if not selected and candidates:
            selected = _hard_cap(candidates, adaptive_chars)
            selector["fallback"] = "hard_cap"
    else:
        selected = _hard_cap(candidates, adaptive_chars)
        selector = {"mode": "legacy_hard_cap", "selected_count": len(selected), "used_chars": sum(len(i.text) for i in selected)}

    final_suff = evaluate_sufficiency(query, selected, structural_required=plan.use_structural, threshold=threshold)
    state = _evidence_state(decision, final_suff.sufficient)
    roots = workspace_roots(root, config)
    snapshot = workspace_fingerprint(root, changed)

    trace.selected = {source: sum(1 for item in selected if item.source == source) for source in {i.source for i in selected}}
    trace.sufficiency = {
        "score": final_suff.score,
        "sufficient": final_suff.sufficient,
        "lexical_coverage": final_suff.lexical_coverage,
        "source_diversity": final_suff.source_diversity,
        "exact_match": final_suff.exact_match,
        "structural_complete": final_suff.structural_complete,
    }
    if plan.use_semantic and not any(item.source == "semantic" for item in specialist_items) and not final_suff.sufficient and "semantic" not in provider_errors:
        trace.fallbacks.append("semantic unavailable or returned no candidates")
    if plan.use_structural and not any(item.source == "code_review_graph" for item in selected):
        trace.fallbacks.append("structural provider unavailable; base broker source fallback used")
    trace.used_chars = sum(len(item.text) for item in selected)

    diagnostics = {
        "retrieval_intent": plan.intent.value,
        "retrieval_reason": plan.reason,
        "workspace_roots": [str(path) for path in roots],
        "workspace_state": snapshot,
        "evidence_state": state,
        "sufficiency": trace.sufficiency,
        "selector": selector,
        "adaptive_context_chars": adaptive_chars,
        "hard_context_chars": budget.context_chars,
        "providers_attempted": trace.providers_attempted,
        "providers_skipped": trace.providers_skipped,
        "provider_errors": provider_errors,
        "fallbacks": trace.fallbacks,
        "stage_latency_ms": trace.stage_latency_ms,
    }
    diagnostics["orchestration"] = build_orchestration_contract(
        decision, diagnostics, changed, len(roots), providers, config
    )
    if write_telemetry and trace_enabled(config, decision.lane.value):
        diagnostics["trace"] = write_trace(root, trace)
    return selected, diagnostics


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
