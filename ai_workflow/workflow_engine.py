from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .budget import ContextBudget, truncate
from .capability_gate import build_model_capability_policy
from .code_review_graph import workspace_graph_fingerprint
from .context_broker import (
    crg_context as default_structural_provider,
    gather as default_base_gather,
)
from .context_selection import select_context
from .config import estimate_tokens
from .deployment_runtime import resolve_runtime_deployment
from .evidence import (
    build_evidence_envelope,
    repository_ids_for_roots,
    trust_class_for_source,
)
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, reciprocal_rank_fusion, tokenize
from .models import ContextItem, Lane, RouteDecision
from .multi_repo_retrieval import plan_repository_retrieval
from .orchestration import build_orchestration_contract
from .provenance import config_digest
from .providers import ProviderStatus
from .retrieval_contracts import ProviderResult
from .retrieval_policy import classify_retrieval_intent, evaluate_sufficiency
from .retrieval_learning import (
    apply_learning_arm,
    prepare_learning_decision,
    write_learning_observation,
)
from .retrieval_scheduler import BoundedRetrievalScheduler, ScheduledCall, SchedulerOutcome
from .retriever_plugins import configured_retrievers, run_retriever_result as default_external_provider
from .run_journal import write_run_journal
from .semantic import semantic_result as default_semantic_provider
from .scip import scip_context as default_scip_provider
from .task_retrieval import TaskRetrievalPolicy, task_retrieval_policy
from .telemetry import RetrievalTrace, trace_enabled, write_trace
from .workspace import workspace_roots
from .workspace_state import workspace_fingerprint


def _provenance(item: ContextItem, workspace_root: Path | None = None) -> ContextItem:
    """Normalize provenance with code-owned trust labels.

    Retrieved text and provider-supplied metadata may describe provenance, but
    they cannot promote themselves into a trusted/authoritative control source.
    """

    metadata = dict(item.metadata)
    provenance = dict(item.provenance)
    provenance["retriever"] = item.source
    provenance["fresh"] = not item.stale
    if workspace_root is not None:
        provenance["workspace_root"] = str(workspace_root.resolve())
    provenance["trust"] = trust_class_for_source(item.source).value
    for key in ("path", "file", "line", "start_line", "end_line", "sha256"):
        if key in metadata:
            provenance[key] = metadata[key]
    return ContextItem(
        item.source,
        item.text,
        item.score,
        item.stale,
        metadata,
        provenance,
    )


def _attach_evidence_envelope(
    item: ContextItem,
    *,
    control_root: Path,
    repository_ids: dict[Path, str],
) -> ContextItem:
    raw_root = item.provenance.get("workspace_root")
    candidate_root = control_root
    if isinstance(raw_root, str) and raw_root.strip():
        try:
            candidate_root = Path(raw_root).resolve()
        except OSError:
            candidate_root = control_root

    repository_id = repository_ids.get(candidate_root)
    if repository_id is None:
        repository_id = repository_ids[control_root]

    envelope = build_evidence_envelope(
        source=item.source,
        text=item.text,
        stale=item.stale,
        metadata=item.metadata,
        provenance=item.provenance,
        repository_id=repository_id,
    )
    return replace(item, evidence=envelope)


def _dedupe_ranked(items: list[ContextItem]) -> list[ContextItem]:
    out: list[ContextItem] = []
    seen: set[str] = set()
    for item in items:
        if item.dedupe_key in seen:
            continue
        seen.add(item.dedupe_key)
        out.append(item)
    return out


def _algorithm_policy(config: dict) -> dict:
    experiments = ((config.get("context") or {}).get("experiments") or {})
    ranker = str(experiments.get("hybrid_ranker", "adaptive")).strip().lower()
    if ranker not in {"adaptive", "source", "bm25", "rrf", "rrf_mmr"}:
        ranker = "adaptive"
    try:
        rrf_k = max(1, int(experiments.get("rrf_k", 60)))
    except (TypeError, ValueError):
        rrf_k = 60
    try:
        mmr_lambda = float(experiments.get("mmr_lambda", 0.75))
    except (TypeError, ValueError):
        mmr_lambda = 0.75
    mmr_lambda = min(1.0, max(0.0, mmr_lambda))
    return {
        "hybrid_ranker": ranker,
        "rrf_k": rrf_k,
        "mmr_lambda": mmr_lambda,
        "disable_early_sufficiency_gate": bool(
            experiments.get("disable_early_sufficiency_gate", False)
        ),
    }


def _hybrid_rank(
    query: str,
    base: list[ContextItem],
    specialist: list[ContextItem],
    limit: int,
    config: dict,
    task_policy: TaskRetrievalPolicy | None = None,
) -> list[ContextItem]:
    candidates = [_provenance(item) for item in [*base, *specialist]]
    if not candidates:
        return []

    policy = _algorithm_policy(config)
    mode = policy["hybrid_ranker"]
    adaptive_mode = mode == "adaptive"
    if mode == "adaptive" and not specialist:
        return _dedupe_ranked(candidates)
    if mode == "adaptive":
        mode = "rrf_mmr"

    source_rank = _dedupe_ranked(
        sorted(candidates, key=lambda item: -item.score)
    )
    lexical_scorer = BM25Scorer()
    lexical_scorer.fit([item.text for item in candidates], candidates)
    lexical_rank = [item for _, item in lexical_scorer.rank(query)]
    lexical_keys = {item.dedupe_key for item in lexical_rank}
    lexical_rank.extend(
        item for item in source_rank if item.dedupe_key not in lexical_keys
    )

    if mode == "source":
        return source_rank[:limit]
    if mode == "bm25":
        return _dedupe_ranked(lexical_rank)[:limit]

    specialist_rank = _dedupe_ranked(
        sorted(
            (_provenance(item) for item in specialist),
            key=lambda item: -item.score,
        )
    )
    fusion_weights = (
        [
            task_policy.source_weight,
            task_policy.lexical_weight,
            task_policy.specialist_weight,
        ]
        if task_policy is not None
        else None
    )
    fused = reciprocal_rank_fusion(
        [source_rank, lexical_rank, specialist_rank],
        key=lambda item: item.dedupe_key,
        k=int(policy["rrf_k"]),
        weights=fusion_weights,
    )
    fused_items = [item for _, item in fused]
    fused_scores = [score for score, _ in fused]
    if mode == "rrf" or len(fused_items) <= 1:
        return fused_items[:limit]

    scorer = BM25Scorer()
    scorer.fit([item.text for item in fused_items], fused_items)
    return maximal_marginal_relevance(
        tokenize(query),
        scorer.docs,
        fused_scores,
        lambda_param=(
            task_policy.mmr_lambda
            if adaptive_mode and task_policy is not None
            else float(policy["mmr_lambda"])
        ),
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


def _adaptive_token_limit(
    budget: ContextBudget,
    score: float,
    config: dict,
) -> int:
    cfg = ((config.get("context") or {}).get("adaptive_budget") or {})
    if not cfg.get("enabled", True):
        return budget.estimated_tokens
    high = float(cfg.get("high_sufficiency_fraction", 0.45))
    medium = float(cfg.get("medium_sufficiency_fraction", 0.7))
    fraction = high if score >= 0.86 else medium if score >= 0.72 else 1.0
    return min(
        budget.estimated_tokens,
        max(1, int(budget.estimated_tokens * fraction)),
    )


def _evidence_state(decision: RouteDecision, sufficient: bool) -> str:
    if sufficient:
        return "sufficient"
    if decision.lane == Lane.ANSWER:
        return "abstain"
    return "requires_exploration"


def _scheduler_settings(config: dict) -> tuple[int, float]:
    cfg = ((config.get("execution") or {}).get("retrieval_scheduler") or {})
    return max(1, int(cfg.get("max_concurrency", 4))), max(0.05, float(cfg.get("global_deadline_seconds", 12.0)))


def _scheduler_error(outcome: SchedulerOutcome) -> dict:
    return {
        "kind": outcome.error_kind or "scheduler_error",
        "message": outcome.error or "retrieval call failed",
        "timed_out": bool(outcome.timed_out),
    }


def _fallback_label(label: str, kind: str) -> str:
    if label == "semantic":
        return f"semantic provider failed: {kind}"
    return f"{label} failed: {kind}"


def _structural_anchor(
    items: list[ContextItem],
) -> tuple[str | None, str | None, Path | None]:
    """Return the first bounded symbol/path anchor and its repository."""

    for item in sorted(
        items,
        key=lambda candidate: (
            bool(candidate.stale),
            -candidate.score,
            candidate.dedupe_key,
        ),
    ):
        metadata = dict(item.metadata)
        symbol = str(
            metadata.get("symbol")
            or metadata.get("qualified_name")
            or ""
        ).strip()
        path = str(
            metadata.get("path")
            or metadata.get("file")
            or ""
        ).strip()

        if not symbol and item.source == "lightweight_index":
            try:
                payload = json.loads(item.text)
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if isinstance(payload, dict):
                symbol = str(
                    payload.get("symbol")
                    or payload.get("qualified_name")
                    or ""
                ).strip()
                path = path or str(
                    payload.get("file")
                    or payload.get("path")
                    or ""
                ).strip()

        if symbol or path:
            raw_root = item.provenance.get("workspace_root")
            repository = (
                Path(str(raw_root)).resolve()
                if raw_root
                else None
            )
            return symbol or None, path or None, repository
    return None, None, None


class WorkflowEngine:
    """Application-level retrieval sequencer with bounded concurrent adapters."""

    def __init__(
        self,
        *,
        base_gather: Callable = default_base_gather,
        semantic_provider: Callable = default_semantic_provider,
        structural_provider: Callable = default_structural_provider,
        scip_provider: Callable = default_scip_provider,
        external_provider: Callable = default_external_provider,
    ) -> None:
        self.base_gather = base_gather
        self.semantic_provider = semantic_provider
        self.structural_provider = structural_provider
        self.scip_provider = scip_provider
        self.external_provider = external_provider

    async def gather_detailed_async(
        self,
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
        run_id: str | None = None,
    ) -> tuple[list[ContextItem], dict]:
        changed = changed_files or []
        execution_run_id = (
            str(run_id).strip() if run_id else str(uuid.uuid4())
        )
        policy_identity: dict[str, Any] = {
            "config_digest": config_digest(config),
            "retrieval_policy_version": str(
                config.get("version", "unknown")
            ),
        }
        plan = classify_retrieval_intent(
            query,
            decision,
            symbol=symbol,
            endpoint=endpoint,
        )
        task_policy = task_retrieval_policy(
            query,
            plan,
            changed_files=changed,
        )
        roots = workspace_roots(root, config)
        max_roots = max(
            1,
            int(((config.get("workspace") or {}).get("max_roots", 4))),
        )
        routing_plan = plan_repository_retrieval(
            Path(root).resolve(),
            roots[:max_roots],
            query,
            changed,
            config,
        )
        selected_routes = list(routing_plan.repositories)
        selected_roots = [route.root for route in selected_routes]
        deployment_assignment = resolve_runtime_deployment(
            root,
            query,
            decision,
            plan.intent.value,
            config,
            changed_files_count=len(changed),
            workspace_roots_count=len(selected_roots),
        )
        learning_decision, learning_path = prepare_learning_decision(
            root,
            query,
            decision,
            plan.intent.value,
            config,
            changed_files_count=len(changed),
            workspace_roots_count=len(roots),
            deployment_assignment=deployment_assignment,
        )
        effective_config = apply_learning_arm(
            config,
            learning_decision.chosen_arm,
        )
        algorithm_policy = _algorithm_policy(effective_config)
        policy_identity["algorithm_policy"] = dict(algorithm_policy)
        policy_identity["task_retrieval_policy"] = task_policy.to_dict()
        trace = RetrievalTrace(
            query,
            decision.lane.value,
            decision.risk.value,
            plan.intent.value,
            run_id=execution_run_id,
            policy_identity=dict(policy_identity),
            budget_chars=budget.context_chars,
        )
        max_concurrency, global_deadline = _scheduler_settings(config)
        scheduler = BoundedRetrievalScheduler(max_concurrency)
        started = time.perf_counter()

        def remaining() -> float:
            return global_deadline - (time.perf_counter() - started)

        route_by_root = {route.root: route for route in selected_routes}

        def routed_item(item: ContextItem, provider_root: Path) -> ContextItem:
            routed = _provenance(item, provider_root)
            route = route_by_root.get(provider_root)
            if route is None:
                return routed
            routed.metadata["repository_tier"] = route.tier
            routed.metadata["repository_prior"] = route.prior
            routed.metadata["repository_relationship"] = route.relationship
            routed.metadata["repository_id"] = route.repository_id
            routed.score *= route.prior
            return routed

        base_calls: list[ScheduledCall] = []
        workspace_root = Path(root).resolve()
        identity_roots = list(
            dict.fromkeys([workspace_root, *selected_roots])
        )
        repository_ids = repository_ids_for_roots(
            workspace_root,
            identity_roots,
            config,
        )

        nested_root_prefixes: list[str] = []
        for known_root in roots:
            if known_root == workspace_root:
                continue
            try:
                relative_known = known_root.relative_to(workspace_root).as_posix()
            except ValueError:
                continue
            nested_root_prefixes.append(relative_known.rstrip("/") + "/")

        def changed_for(candidate_root: Path) -> list[str]:
            if candidate_root == workspace_root:
                return [
                    path
                    for path in changed
                    if not any(
                        path.startswith(prefix)
                        for prefix in nested_root_prefixes
                    )
                ]
            try:
                relative_root = candidate_root.relative_to(
                    workspace_root
                ).as_posix()
            except ValueError:
                return []
            prefix = relative_root.rstrip("/") + "/"
            return [
                path[len(prefix):]
                for path in changed
                if path.startswith(prefix)
            ]

        for index, candidate_root in enumerate(selected_roots):
            label = "base" if index == 0 else f"workspace:{candidate_root.name}"
            trace.providers_attempted.append(label)
            candidate_changed = changed_for(candidate_root)
            base_calls.append(
                ScheduledCall(
                    label,
                    partial(
                        self.base_gather,
                        candidate_root,
                        query,
                        decision,
                        budget,
                        config,
                        providers,
                        symbol,
                        endpoint,
                        candidate_changed,
                    ),
                )
            )

        base_outcomes = await scheduler.run(base_calls, max(0.001, remaining()))
        base_items: list[ContextItem] = []
        provider_errors: dict[str, dict] = {}
        deadline_labels: list[str] = []
        for outcome, route in zip(base_outcomes, selected_routes, strict=True):
            candidate_root = route.root
            trace.stage_latency_ms[outcome.label] = round(outcome.latency_ms, 2)
            if outcome.ok and isinstance(outcome.value, list):
                trace.candidates[outcome.label] = len(outcome.value)
                base_items.extend(
                    routed_item(item, candidate_root)
                    for item in outcome.value
                )
            else:
                trace.candidates[outcome.label] = 0
                provider_errors[outcome.label] = _scheduler_error(outcome)
                kind = outcome.error_kind or "scheduler_error"
                trace.fallbacks.append(_fallback_label(outcome.label, kind))
                if outcome.timed_out:
                    deadline_labels.append(outcome.label)

        threshold = float((((config.get("context") or {}).get("sufficiency") or {}).get("threshold", 0.72)))
        suff = evaluate_sufficiency(
            query,
            base_items,
            structural_required=plan.use_structural,
            structural_patterns=plan.structural_patterns,
            threshold=threshold,
        )
        specialist_items: list[ContextItem] = []
        specialist_calls: list[ScheduledCall] = []
        specialist_kinds: list[str] = []
        specialist_roots: list[Path] = []

        early_gate_open = (
            not suff.sufficient
            or algorithm_policy["disable_early_sufficiency_gate"]
        )
        should_semantic = plan.use_semantic and early_gate_open
        provider_limit = int(config["context"].get("max_results_per_source", 6))
        if should_semantic and providers.semantic:
            for candidate_root in selected_roots:
                label = (
                    "semantic"
                    if len(selected_roots) == 1
                    else f"semantic:{candidate_root.name}"
                )
                trace.providers_attempted.append(label)
                specialist_calls.append(
                    ScheduledCall(
                        label,
                        partial(
                            self.semantic_provider,
                            candidate_root,
                            query,
                            config,
                            provider_limit,
                        ),
                    )
                )
                specialist_kinds.append("semantic")
                specialist_roots.append(candidate_root)
        elif plan.use_semantic:
            trace.providers_skipped["semantic"] = "provider not configured" if not providers.semantic else "base evidence sufficient"

        if early_gate_open:
            for spec in configured_retrievers(config, plan.intent.value):
                name = str(spec.get("name", "external"))
                label = f"external:{name}"
                trace.providers_attempted.append(label)
                specialist_calls.append(
                    ScheduledCall(
                        label,
                        partial(
                            self.external_provider,
                            root,
                            query,
                            plan.intent.value,
                            spec,
                            provider_limit,
                        ),
                    )
                )
                specialist_kinds.append(label)
                specialist_roots.append(workspace_root)

        specialist_outcomes: list[SchedulerOutcome] = []
        if specialist_calls:
            time_left = remaining()
            if time_left > 0:
                specialist_outcomes = await scheduler.run(specialist_calls, time_left)
            else:
                specialist_outcomes = [
                    SchedulerOutcome(
                        call.label,
                        error=f"global retrieval deadline exceeded after {global_deadline:g} seconds",
                        error_kind="deadline",
                        timed_out=True,
                    )
                    for call in specialist_calls
                ]

        for outcome, _kind, provider_root in zip(
            specialist_outcomes,
            specialist_kinds,
            specialist_roots,
            strict=True,
        ):
            if not outcome.ok or not isinstance(outcome.value, ProviderResult):
                trace.stage_latency_ms[outcome.label] = round(outcome.latency_ms, 2)
                trace.candidates[outcome.label] = 0
                provider_errors[outcome.label] = _scheduler_error(outcome)
                error_kind = outcome.error_kind or "scheduler_error"
                trace.fallbacks.append(_fallback_label(outcome.label, error_kind))
                if outcome.timed_out:
                    deadline_labels.append(outcome.label)
                continue

            result = outcome.value
            trace.stage_latency_ms[outcome.label] = round(result.latency_ms or outcome.latency_ms, 2)
            trace.candidates[outcome.label] = len(result.items)
            if result.error:
                provider_errors[outcome.label] = result.error_dict() or {"kind": "provider_error", "message": result.error}
                error_kind = result.error_kind or "provider_error"
                trace.fallbacks.append(_fallback_label(outcome.label, error_kind))
            specialist_items.extend(
                routed_item(item, provider_root)
                for item in result.items
            )

        pre_expansion_suff = evaluate_sufficiency(
            query,
            [*base_items, *specialist_items],
            structural_required=plan.use_structural,
            structural_patterns=plan.structural_patterns,
            threshold=threshold,
        )
        if plan.use_structural and not pre_expansion_suff.structural_complete:
            (
                discovered_symbol,
                anchor_path,
                anchor_root,
            ) = _structural_anchor([*specialist_items, *base_items])
            anchor_symbol = symbol or discovered_symbol
            structural_root = anchor_root
            if structural_root is None and len(selected_roots) == 1:
                structural_root = selected_roots[0]

            structural_files = (
                changed_for(structural_root)
                if structural_root is not None
                else []
            )
            if not structural_files and anchor_path:
                structural_files = [anchor_path]
            can_expand = bool(
                structural_root is not None
                and (
                    anchor_symbol
                    or structural_files
                    or "architecture" in plan.structural_patterns
                    or "references_to" in plan.structural_patterns
                )
            )

            if not can_expand or structural_root is None:
                trace.providers_skipped["structural-expansion"] = (
                    "no unambiguous repository anchor"
                )
                if "references_to" in plan.structural_patterns:
                    trace.providers_skipped["scip-structural-expansion"] = (
                        "no unambiguous repository anchor"
                    )
            else:
                structural_steps = [
                    (
                        "structural-expansion",
                        providers.code_review_graph,
                        self.structural_provider,
                        True,
                    ),
                    (
                        "scip-structural-expansion",
                        providers.scip,
                        self.scip_provider,
                        "references_to" in plan.structural_patterns,
                    ),
                ]
                for label, enabled, provider, relevant in structural_steps:
                    current_suff = evaluate_sufficiency(
                        query,
                        [*base_items, *specialist_items],
                        structural_required=True,
                        structural_patterns=plan.structural_patterns,
                        threshold=threshold,
                    )
                    if current_suff.structural_complete:
                        break
                    if not relevant:
                        continue
                    if not enabled:
                        trace.providers_skipped[label] = (
                            "provider not configured"
                        )
                        continue

                    trace.providers_attempted.append(label)
                    time_left = remaining()
                    if time_left > 0:
                        outcomes = await scheduler.run(
                            [
                                ScheduledCall(
                                    label,
                                    partial(
                                        provider,
                                        structural_root,
                                        query,
                                        anchor_symbol,
                                        structural_files,
                                        provider_limit,
                                        patterns=plan.structural_patterns,
                                    ),
                                )
                            ],
                            time_left,
                        )
                        outcome = outcomes[0]
                    else:
                        outcome = SchedulerOutcome(
                            label,
                            error=(
                                "global retrieval deadline exceeded after "
                                f"{global_deadline:g} seconds"
                            ),
                            error_kind="deadline",
                            timed_out=True,
                        )

                    trace.stage_latency_ms[label] = round(
                        outcome.latency_ms,
                        2,
                    )
                    if outcome.ok and isinstance(outcome.value, list):
                        trace.candidates[label] = len(outcome.value)
                        specialist_items.extend(
                            routed_item(item, structural_root)
                            for item in outcome.value
                        )
                    else:
                        trace.candidates[label] = 0
                        provider_errors[label] = _scheduler_error(outcome)
                        kind = outcome.error_kind or "scheduler_error"
                        trace.fallbacks.append(
                            _fallback_label(label, kind)
                        )
                        if outcome.timed_out:
                            deadline_labels.append(label)

        limit = provider_limit * 3
        candidates = _hybrid_rank(
            query,
            base_items,
            specialist_items,
            limit,
            effective_config,
            task_policy,
        )
        suff = evaluate_sufficiency(
            query,
            candidates,
            structural_required=plan.use_structural,
            structural_patterns=plan.structural_patterns,
            threshold=threshold,
        )
        adaptive_chars = _adaptive_char_limit(budget, suff.score, config)
        adaptive_tokens = _adaptive_token_limit(budget, suff.score, config)

        selector_cfg = ((config.get("context") or {}).get("selector") or {})
        if selector_cfg.get("enabled", True):
            structural_sources = tuple(
                dict.fromkeys(
                    item.source
                    for item in candidates
                    if bool(item.metadata.get("structural_valid"))
                    and (
                        not plan.structural_patterns
                        or str(item.metadata.get("pattern") or "")
                        in plan.structural_patterns
                    )
                )
            )
            mandatory_sources = (
                structural_sources
                if (
                    plan.use_structural
                    and selector_cfg.get(
                        "mandatory_structural_evidence",
                        True,
                    )
                )
                else ()
            )
            selected, selector = select_context(
                query,
                candidates,
                adaptive_chars,
                config,
                mandatory_sources=mandatory_sources,
                budget_tokens=adaptive_tokens,
            )
            if not selected and candidates:
                fallback = _hard_cap(candidates, adaptive_chars)
                selected = []
                fallback_tokens = 0
                for item in fallback:
                    item_tokens = estimate_tokens(item.text)
                    if fallback_tokens + item_tokens > adaptive_tokens:
                        continue
                    selected.append(item)
                    fallback_tokens += item_tokens
                selector["fallback"] = "hard_cap_token_bounded"
                selector["used_chars"] = sum(len(item.text) for item in selected)
                selector["used_tokens"] = fallback_tokens
        else:
            selected = _hard_cap(candidates, adaptive_chars)
            selector = {"mode": "legacy_hard_cap", "selected_count": len(selected), "used_chars": sum(len(i.text) for i in selected)}

        selected = [
            _attach_evidence_envelope(
                item,
                control_root=workspace_root,
                repository_ids=repository_ids,
            )
            for item in selected
        ]

        final_suff = evaluate_sufficiency(
            query,
            selected,
            structural_required=plan.use_structural,
            structural_patterns=plan.structural_patterns,
            threshold=threshold,
        )
        state = _evidence_state(decision, final_suff.sufficient)
        snapshot = workspace_fingerprint(root, changed)
        graph_state = workspace_graph_fingerprint(root, config)
        trace.workspace_fingerprint = str(
            snapshot.get("fingerprint", "")
        )
        trace.graph_fingerprint = str(
            graph_state.get("fingerprint", "")
        )

        trace.selected = {source: sum(1 for item in selected if item.source == source) for source in {i.source for i in selected}}
        trace.sufficiency = {
            "score": final_suff.score,
            "sufficient": final_suff.sufficient,
            "lexical_coverage": final_suff.lexical_coverage,
            "source_diversity": final_suff.source_diversity,
            "exact_match": final_suff.exact_match,
            "structural_complete": final_suff.structural_complete,
            "structural_patterns": list(plan.structural_patterns),
        }
        if plan.use_semantic and not any(item.source == "semantic" for item in specialist_items) and not final_suff.sufficient and "semantic" not in provider_errors:
            trace.fallbacks.append("semantic unavailable or returned no candidates")
        if plan.use_structural and not final_suff.structural_complete:
            trace.fallbacks.append(
                "structural evidence incomplete; source fallback used"
            )
        trace.used_chars = sum(len(item.text) for item in selected)

        elapsed_ms = (time.perf_counter() - started) * 1000
        diagnostics: dict[str, Any] = {
            "run_id": execution_run_id,
            "retrieval_intent": plan.intent.value,
            "retrieval_reason": plan.reason,
            "algorithm_policy": algorithm_policy,
            "task_retrieval_policy": task_policy.to_dict(),
            "policy_identity": policy_identity,
            "workspace_roots": [str(path) for path in roots],
            "repository_routing": routing_plan.to_dict(),
            "workspace_state": snapshot,
            "graph_state": graph_state,
            "evidence_state": state,
            "evidence_contract": {
                "schema": "evidence-v1",
                "selected_count": len(selected),
                "authority": "evidence_only",
            },
            "sufficiency": trace.sufficiency,
            "selector": selector,
            "adaptive_context_chars": adaptive_chars,
            "hard_context_chars": budget.context_chars,
            "adaptive_context_tokens": adaptive_tokens,
            "hard_context_tokens": budget.estimated_tokens,
            "providers_attempted": trace.providers_attempted,
            "providers_skipped": trace.providers_skipped,
            "provider_errors": provider_errors,
            "fallbacks": trace.fallbacks,
            "stage_latency_ms": trace.stage_latency_ms,
            "scheduler": {
                "max_concurrency": max_concurrency,
                "global_deadline_seconds": global_deadline,
                "deadline_exceeded": bool(deadline_labels),
                "deadline_labels": deadline_labels,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        }
        if learning_decision.mode != "off":
            diagnostics["learning"] = {
                **learning_decision.to_dict(),
                "decision_logged": learning_path is not None,
                "decision_path": (
                    Path(learning_path).relative_to(root.resolve()).as_posix()
                    if learning_path is not None
                    else None
                ),
            }
        orchestration_contract = build_orchestration_contract(
            decision, diagnostics, changed, len(selected_roots), providers, config
        )
        diagnostics["orchestration"] = orchestration_contract
        diagnostics["authorization_policy"] = build_model_capability_policy(
            decision,
            orchestration_contract,
            selected,
        ).to_dict()
        if learning_path is not None:
            try:
                observation_path = write_learning_observation(
                    root,
                    learning_decision.decision_id,
                    elapsed_ms=elapsed_ms,
                    used_chars=trace.used_chars,
                    fallback_count=len(trace.fallbacks),
                    sufficiency_score=final_suff.score,
                    evidence_state=state,
                    config=config,
                )
                diagnostics["learning"]["observation_logged"] = True
                diagnostics["learning"]["observation_path"] = (
                    Path(observation_path)
                    .relative_to(root.resolve())
                    .as_posix()
                )
            except OSError:
                diagnostics["learning"]["observation_logged"] = False
                diagnostics["learning"]["observation_path"] = None
        if write_telemetry and trace_enabled(config, decision.lane.value):
            diagnostics["trace"] = write_trace(root, trace, config)
            safe_error_kinds = {
                name: {
                    "kind": str(error.get("kind") or "provider_error"),
                    "timed_out": bool(error.get("timed_out", False)),
                }
                for name, error in provider_errors.items()
            }
            safe_metadata_keys = {
                "path",
                "file",
                "line",
                "start_line",
                "end_line",
                "sha256",
                "symbol",
                "endpoint",
                "pattern",
                "role",
                "language",
            }
            safe_provenance_keys = {
                "path",
                "file",
                "line",
                "start_line",
                "end_line",
                "sha256",
                "retriever",
                "fresh",
                "trust",
            }
            journal_record = {
                "run_id": execution_run_id,
                "policy_identity": policy_identity,
                "workspace_state": {
                    "fingerprint": snapshot.get("fingerprint"),
                    "git_head": snapshot.get("git_head"),
                },
                "graph_state": graph_state,
                "changed_files": list(changed),
                "retrieval": {
                    "retrieval_intent": plan.intent.value,
                    "retrieval_reason": plan.reason,
                    "evidence_state": state,
                    "providers_attempted": list(
                        trace.providers_attempted
                    ),
                    "providers_skipped": dict(
                        trace.providers_skipped
                    ),
                    "provider_errors": safe_error_kinds,
                    "algorithm_policy": algorithm_policy,
                    "sufficiency": dict(trace.sufficiency),
                    "selector": selector,
                    "fallbacks": list(trace.fallbacks),
                    "scheduler": dict(diagnostics["scheduler"]),
                    "authorization_policy": dict(
                        diagnostics["authorization_policy"]
                    ),
                },
                "selected_evidence": [
                    {
                        "source": item.source,
                        "dedupe_key": item.dedupe_key,
                        "stale": item.stale,
                        "evidence": (
                            item.evidence.to_dict()
                            if item.evidence is not None
                            else None
                        ),
                        "metadata": {
                            key: value
                            for key, value in item.metadata.items()
                            if key in safe_metadata_keys
                        },
                        "provenance": {
                            key: value
                            for key, value in item.provenance.items()
                            if key in safe_provenance_keys
                        },
                    }
                    for item in selected
                ],
            }
            try:
                diagnostics["journal"] = write_run_journal(
                    root,
                    journal_record,
                )
            except (OSError, ValueError):
                diagnostics["journal"] = None
        return selected, diagnostics

    def gather_detailed(self, *args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.gather_detailed_async(*args, **kwargs))
        raise RuntimeError("WorkflowEngine.gather_detailed() cannot run inside an event loop; use gather_detailed_async()")
