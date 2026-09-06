from __future__ import annotations

import time
from pathlib import Path

from .budget import ContextBudget, truncate
from .context_broker import gather as gather_base
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, reciprocal_rank_fusion, tokenize
from .models import ContextItem, RouteDecision
from .providers import ProviderStatus
from .retrieval_policy import classify_retrieval_intent, evaluate_sufficiency
from .semantic import semantic_context
from .telemetry import RetrievalTrace, trace_enabled, write_trace


def _provenance(item: ContextItem) -> ContextItem:
    metadata = dict(item.metadata)
    provenance = dict(item.provenance)
    provenance.setdefault("retriever", item.source)
    provenance.setdefault("fresh", not item.stale)
    if item.source in {"lightweight_index", "targeted_source", "code_review_graph", "semantic", "test_resolver"}:
        provenance.setdefault("trust", "untrusted_repository_content")
    elif item.source in {"durable_memory", "hot_cache", "research_cache"}:
        provenance.setdefault("trust", "generated_or_cached_context")
    else:
        provenance.setdefault("trust", "context_data")
    for key in ("path", "file", "line", "start_line", "end_line", "sha256"):
        if key in metadata and key not in provenance:
            provenance[key] = metadata[key]
    return ContextItem(item.source, item.text, item.score, item.stale, metadata, provenance)


def _hybrid_rank(query: str, lexical: list[ContextItem], semantic: list[ContextItem], limit: int) -> list[ContextItem]:
    candidates = [_provenance(item) for item in [*lexical, *semantic]]
    if not candidates:
        return []
    lexical_scorer = BM25Scorer()
    lexical_scorer.fit([item.text for item in candidates], candidates)
    lexical_rank = [item for _, item in lexical_scorer.rank(query)]
    semantic_rank = sorted(semantic, key=lambda item: -item.score)
    source_rank = sorted(candidates, key=lambda item: -item.score)
    fused = reciprocal_rank_fusion(
        [source_rank, lexical_rank, semantic_rank],
        key=lambda item: item.dedupe_key,
    )
    fused_items = [item for _, item in fused]
    fused_scores = [score for score, _ in fused]
    if len(fused_items) <= 1:
        return fused_items[:limit]
    scorer = BM25Scorer()
    scorer.fit([item.text for item in fused_items], fused_items)
    diversified = maximal_marginal_relevance(
        tokenize(query), scorer.docs, fused_scores, lambda_param=0.75, max_items=min(limit, len(fused_items))
    )
    return diversified


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
    if score >= 0.86:
        fraction = high
    elif score >= 0.72:
        fraction = medium
    else:
        fraction = 1.0
    return min(budget.context_chars, max(minimum, int(budget.context_chars * fraction)))


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
    plan = classify_retrieval_intent(query, decision, symbol=symbol, endpoint=endpoint)
    trace = RetrievalTrace(query, decision.lane.value, decision.risk.value, plan.intent.value, budget_chars=budget.context_chars)

    start = time.perf_counter()
    trace.providers_attempted.append("lexical/base")
    base_items = gather_base(root, query, decision, budget, config, providers, symbol, endpoint, changed_files or [])
    trace.stage_latency_ms["base"] = round((time.perf_counter() - start) * 1000, 2)
    trace.candidates["base"] = len(base_items)
    base_items = [_provenance(item) for item in base_items]

    threshold = float((((config.get("context") or {}).get("sufficiency") or {}).get("threshold", 0.72)))
    suff = evaluate_sufficiency(query, base_items, structural_required=plan.use_structural, threshold=threshold)

    semantic_items: list[ContextItem] = []
    should_semantic = plan.use_semantic and not suff.sufficient
    if should_semantic and providers.semantic:
        trace.providers_attempted.append("semantic")
        start = time.perf_counter()
        semantic_items = semantic_context(root, query, config, int(config["context"].get("max_results_per_source", 6)))
        trace.stage_latency_ms["semantic"] = round((time.perf_counter() - start) * 1000, 2)
        trace.candidates["semantic"] = len(semantic_items)
    elif plan.use_semantic:
        trace.providers_skipped["semantic"] = "provider not configured" if not providers.semantic else "base evidence sufficient"

    limit = int(config["context"].get("max_results_per_source", 6)) * 3
    if semantic_items:
        selected = _hybrid_rank(query, base_items, semantic_items, limit)
        suff = evaluate_sufficiency(query, selected, structural_required=plan.use_structural, threshold=threshold)
    else:
        selected = base_items

    adaptive_chars = _adaptive_char_limit(budget, suff.score, config)
    selected = _hard_cap(selected, adaptive_chars)
    trace.selected = {source: sum(1 for item in selected if item.source == source) for source in {i.source for i in selected}}
    trace.sufficiency = {
        "score": suff.score,
        "sufficient": suff.sufficient,
        "lexical_coverage": suff.lexical_coverage,
        "source_diversity": suff.source_diversity,
        "exact_match": suff.exact_match,
        "structural_complete": suff.structural_complete,
    }
    if plan.use_semantic and not semantic_items and not suff.sufficient:
        trace.fallbacks.append("semantic unavailable or returned no candidates")
    if plan.use_structural and not any(item.source == "code_review_graph" for item in selected):
        trace.fallbacks.append("structural provider unavailable; base broker source fallback used")
    trace.used_chars = sum(len(item.text) for item in selected)

    diagnostics = {
        "retrieval_intent": plan.intent.value,
        "retrieval_reason": plan.reason,
        "sufficiency": trace.sufficiency,
        "adaptive_context_chars": adaptive_chars,
        "hard_context_chars": budget.context_chars,
        "providers_attempted": trace.providers_attempted,
        "providers_skipped": trace.providers_skipped,
        "fallbacks": trace.fallbacks,
        "stage_latency_ms": trace.stage_latency_ms,
    }
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
