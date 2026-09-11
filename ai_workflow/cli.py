from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .adaptive_broker import gather_detailed
from .benchmark import load_tasks, run_benchmark
from .benchmark_corpus import (
    corpus_summary,
    load_corpus_document,
)
from .benchmark_ablation import PROFILE_ORDER, run_ablation_suite
from .benchmark_algorithm_ablation import (
    ALGORITHM_PROFILE_ORDER,
    run_algorithm_ablation_suite,
)
from .benchmark_intervention import (
    SEED_MODES,
    build_seed_intervention_manifest,
    run_seed_interventions,
)
from .benchmark_calibration import calibrate_sufficiency_threshold
from .benchmark_policy_advisor import build_safe_policy_advisor
from .benchmark_protocol import capture_repository_snapshot
from .benchmark_statistics import analyze_seed_report
from .bootstrap import WORKSPACE_AGENTS_RELATIVE, WORKSPACE_PROJECT_RELATIVE, bootstrap, setup
from .budget import budget_for
from .classifier import classify
from .compress import compress_text
from .config import estimate_tokens, find_project_root, load_config
from .contextual_features import DEFAULT_POLICY_FIELDS, FEATURE_FIELDS
from .contextual_policy import build_contextual_policy_report
from .context_broker import detect_changed_files
from .deployment_guardrails import evaluate_live_guardrails
from .deployment_incident import (
    create_incident_bundle,
    verify_incident_bundle,
    write_incident_bundle,
)
from .deployment_state import (
    create_deployment_state,
    load_deployment_state,
    update_deployment_state_file,
    verify_deployment_state,
    write_new_deployment_state,
)
from .doctor import run as doctor_run
from .handoff import handoff_path, render as render_handoff, validate as validate_handoff
from .indexer import build_indexes, incremental_indexes
from .io_utils import atomic_write_json, atomic_write_text
from .observability_export import (
    build_deployment_metrics,
    write_deployment_metrics,
)
from .memory import add_memory, export_memory_jsonl, list_memories, prune_stale, search_memory
from .learning_ope import evaluate_learning_policies
from .policy_manifest import (
    create_policy_manifest,
    verify_policy_manifest,
)
from .production_store import (
    mirror_learning_event,
    production_store_status,
    reconcile_learning_store,
    sync_learning_store,
)
from .retrieval_learning import (
    SAFE_EXPLORATION_ARMS,
    learning_status,
    record_verified_outcome,
)
from .shadow_policy import evaluate_shadow_policy
from .providers import detect, execution_provider, model_tier
from .repository_registry import refresh_registry, registry_summary, set_repository_included
from .telemetry import policy_recommendations, summarize_traces
from .verify import verify


def _root(args) -> Path:
    return Path(args.root).resolve() if getattr(args, "root", None) else find_project_root()


def _json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_setup(args):
    index_mode = (
        "none"
        if getattr(args, "no_index", False)
        else "full"
        if getattr(args, "full_index", False)
        else "auto"
    )
    result = setup(
        _root(args),
        args.project_name,
        create=bool(getattr(args, "create", False)),
        index_mode=index_mode,
        legacy_root_files=bool(getattr(args, "legacy_root_files", False)),
        discover=not bool(getattr(args, "no_discover_repos", False)),
        discovery_depth=int(getattr(args, "discover_depth", 3)),
    )
    if args.json:
        _json(result)
        return
    print(f"AI Workflow ready: {result['project']}")
    print(f"Root: {result['root']}")
    if result["created"]:
        print("Created: " + ", ".join(result["created"]))
    if result["preserved"]:
        print("Preserved: " + ", ".join(result["preserved"]))
    registry = result.get("repository_registry") or {}
    if registry.get("status") == "created":
        print(
            "Repositories discovered: "
            f"{registry.get('discovered', 0)}; review {registry.get('path')} before enabling multi-repo roots"
        )
    print("Next: " + result["next"])


def cmd_bootstrap(args):
    try:
        _json(bootstrap(_root(args), args.project_name))
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_init(args):
    root = _root(args)
    agents = root / WORKSPACE_AGENTS_RELATIVE
    legacy_agents = root / "AGENTS.md"
    try:
        load_config(root)
    except FileNotFoundError as exc:
        raise SystemExit(
            "Copy the workflow template into the project or run `ai-workflow bootstrap --project-name NAME`; workspace config and agent rules are required."
        ) from exc
    agents_path = agents if agents.exists() else legacy_agents
    if not agents_path.exists():
        raise SystemExit(
            "AGENTS template missing; run `ai-workflow setup` to recreate clean workspace files."
        )
    text = agents_path.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", args.project_name)
    atomic_write_text(root / WORKSPACE_PROJECT_RELATIVE, ".\n")
    atomic_write_text(agents_path, text)
    _json(
        {
            "status": "initialized",
            "project": args.project_name,
            "root": str(root),
            "index": build_indexes(root),
        }
    )


def _decision(root: Path, task: str):
    config = load_config(root)
    providers = detect(root, config)
    decision = classify(task, config)
    budget = budget_for(decision.lane, config)
    provider = execution_provider(decision.lane, config, providers)
    return config, providers, decision, budget, provider, model_tier(decision, config)


def cmd_route(args):
    root = _root(args)
    config, providers, decision, budget, provider, model = _decision(root, args.task)
    _json(
        {
            **decision.to_dict(),
            "execution_provider": provider,
            "model_tier": model,
            "providers": providers.to_dict(),
            "budget": {
                "estimated_context_tokens": budget.estimated_tokens,
                "max_output_tokens": budget.output_tokens,
            },
        }
    )


def cmd_repos_list(args):
    root = _root(args)
    _json(registry_summary(root, load_config(root)))


def cmd_repos_refresh(args):
    root = _root(args)
    config = load_config(root)
    discovery = ((config.get("workspace") or {}).get("discovery") or {})
    depth = (
        int(args.discover_depth)
        if args.discover_depth is not None
        else int(discovery.get("max_depth", 3))
    )
    try:
        result = refresh_registry(root, max_depth=depth, config=config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _json(result)


def _cmd_repos_set(args, included: bool):
    root = _root(args)
    config = load_config(root)
    try:
        result = set_repository_included(root, args.repository, included, config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    _json(result)


def cmd_repos_include(args):
    _cmd_repos_set(args, True)


def cmd_repos_exclude(args):
    _cmd_repos_set(args, False)


def _resolve_changed(root: Path, explicit: list[str]) -> list[str]:
    return explicit if explicit else detect_changed_files(root)


def _format_brief(packet: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(packet, indent=2, ensure_ascii=False)
    retrieval = packet.get("retrieval", {}) or {}
    orchestration = retrieval.get("orchestration", {}) or {}
    skills = orchestration.get("superpowers_skills", []) or []
    crg_plan = orchestration.get("crg_plan", []) or []
    evidence = retrieval.get("evidence_state", "unknown")
    fingerprint = (retrieval.get("workspace_state") or {}).get("fingerprint", "unknown")
    ctx_text = "\n".join(i["text"] for i in packet.get("context", []) if i.get("text"))
    if fmt == "markdown":
        lines = [
            f"# Brief: {packet['task']}",
            f"**Lane**: {packet['lane']} | **Risk**: {packet['risk']} | **Confidence**: {packet.get('confidence', 0):.2f} | **Model tier**: {packet['model_tier']}",
            f"**Retrieval**: {retrieval.get('retrieval_intent', 'unknown')} | **Evidence**: {evidence}",
            f"**Execution**: {packet['execution_provider']} — {packet.get('execution_hint', '')}",
            f"**Superpowers**: {', '.join(skills) or 'none'}",
            f"**CRG**: {', '.join(crg_plan) or 'none'}",
            f"**Workspace state**: {fingerprint}",
            f"**Budget**: {packet['budget']['estimated_context_tokens']} est. tokens | {packet['budget']['max_output_tokens']} output",
            f"**Changed files**: {', '.join(packet.get('changed_files_detected', [])) or 'none detected'}",
            "",
            "## Context",
            "",
            ctx_text or "(no context gathered)",
        ]
        return "\n".join(lines)
    lines = [
        f"[TASK] {packet['task']}",
        f"[LANE] {packet['lane']} [RISK] {packet['risk']} [CONFIDENCE] {packet.get('confidence', 0):.2f} [MODEL_TIER] {packet['model_tier']}",
        f"[RETRIEVAL_INTENT] {retrieval.get('retrieval_intent', 'unknown')}",
        f"[EVIDENCE_STATE] {evidence}",
        f"[WORKSPACE_FINGERPRINT] {fingerprint}",
        f"[EXECUTION] {packet['execution_provider']}",
        f"[SUPERPOWERS_SKILLS] {', '.join(skills) or 'none'}",
        f"[CRG_PLAN] {', '.join(crg_plan) or 'none'}",
        f"[AGENT_SLOTS] {orchestration.get('agent_slots', 1)}",
        f"[HINT] {packet.get('execution_hint', '')}",
        f"[BUDGET] context={packet['budget']['estimated_context_tokens']}tok output={packet['budget']['max_output_tokens']}tok",
        f"[CHANGED_FILES] {', '.join(packet.get('changed_files_detected', [])) or 'none'}",
    ]
    if packet.get("context"):
        lines += ["[CONTEXT_START]", ctx_text, "[CONTEXT_END]"]
    lines.append(
        f"[INVARIANTS] {packet.get('invariants', 'preserve existing contracts unless task explicitly changes them')}"
    )
    return "\n".join(lines)


def cmd_brief(args):
    root = _root(args)
    config, providers, decision, budget, provider, model = _decision(root, args.task)
    changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        changed,
        write_telemetry=(decision.lane.value != "answer" or args.trace),
    )
    packet = {
        "task": args.task,
        **decision.to_dict(),
        "execution_provider": provider,
        "model_tier": model,
        "execution_hint": (
            "Follow the emitted Superpowers skill sequence and CRG plan; do not edit while evidence_state=requires_exploration."
            if provider == "superpowers"
            else "Use native lightweight execution."
            if decision.lane.value == "small"
            else "Use native Plan -> Build -> Review fallback."
            if decision.lane.value == "full"
            else "Answer directly; no implementation workflow."
        ),
        "budget": {
            "estimated_context_tokens": budget.estimated_tokens,
            "max_output_tokens": budget.output_tokens,
        },
        "retrieval": retrieval,
        "context": [i.to_dict() for i in items],
        "estimated_context_tokens_used": estimate_tokens("\n".join(i.text for i in items)),
        "output_compression": "rtk" if providers.rtk else "builtin",
        "changed_files_detected": changed,
    }
    if args.write_handoff and decision.lane.value != "answer":
        text = render_handoff(decision, provider, [i.source for i in items], args.task)
        path = handoff_path(root)
        atomic_write_text(path, text)
        packet["handoff_written"] = path.relative_to(root).as_posix()
    if decision.lane.value != "answer":
        atomic_write_json(root / "ai-workspace" / "generated" / "last-brief.json", packet)
    print(_format_brief(packet, getattr(args, "format", "json")))


def cmd_context(args):
    root = _root(args)
    config, providers, decision, budget, _, _ = _decision(root, args.task)
    changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(
        root,
        args.task,
        decision,
        budget,
        config,
        providers,
        args.symbol,
        args.endpoint,
        changed,
        write_telemetry=args.trace,
    )
    _json(
        {
            "lane": decision.lane.value,
            "risk": decision.risk.value,
            "confidence": decision.confidence,
            "budget": budget.estimated_tokens,
            "retrieval": retrieval,
            "items": [i.to_dict() for i in items],
            "estimated_tokens": estimate_tokens("\n".join(i.text for i in items)),
        }
    )


def cmd_index(args):
    root = _root(args)
    if getattr(args, "incremental", False):
        _json(
            incremental_indexes(
                root,
                strict_hash=bool(getattr(args, "strict_hash", False)),
            )
        )
    else:
        _json(build_indexes(root))


def cmd_doctor(args):
    root = _root(args)
    result, ok = doctor_run(root, load_config(root))
    _json(result)
    if args.strict and not ok:
        raise SystemExit(1)


def cmd_handoff(args):
    root = _root(args)
    errors = validate_handoff(root, int(load_config(root)["handoff"].get("max_lines", 30)))
    _json({"valid": not errors, "errors": errors})
    if errors:
        raise SystemExit(1)


def cmd_memory_add(args):
    _json(
        add_memory(
            _root(args),
            args.type,
            args.keywords,
            args.summary,
            args.evidence or "",
            args.file or [],
            args.confidence,
        )
    )


def cmd_memory_search(args):
    root = _root(args)
    cfg = load_config(root)
    _json(
        search_memory(
            root,
            args.query,
            args.limit or int(cfg["memory"]["max_results"]),
            float(cfg["memory"].get("minimum_confidence", 0.55)),
        )
    )


def cmd_memory_list(args):
    _json(list_memories(_root(args)))


def cmd_memory_prune(args):
    _json(prune_stale(_root(args)))


def cmd_memory_export(args):
    destination = Path(args.output).resolve()
    count = export_memory_jsonl(_root(args), destination)
    _json({"format": "jsonl", "output": str(destination), "records": count})


def cmd_compress(args):
    text = (
        Path(args.file).read_text(encoding="utf-8", errors="replace")
        if args.file
        else sys.stdin.read()
    )
    sys.stdout.write(compress_text(text, args.max_lines, args.max_chars))


def cmd_verify(args):
    root = _root(args)
    cfg = load_config(root)
    result = verify(root, args.check or [], int(cfg["handoff"].get("max_lines", 30)))
    _json(result)
    if args.strict and not result["ok"]:
        raise SystemExit(1)


def cmd_benchmark_corpus_validate(args):
    document = load_corpus_document(Path(args.input))
    summary = corpus_summary(document)
    _json(summary)
    if args.require_ready and not summary["publication_readiness"]["ready"]:
        raise SystemExit(1)


def cmd_benchmark_corpus_snapshot(args):
    root = _root(args)
    candidate = (root / args.repository).resolve()
    if not candidate.is_relative_to(root):
        raise SystemExit("benchmark repository must stay inside project root")
    if not candidate.is_dir():
        raise SystemExit(
            f"benchmark repository does not exist: {args.repository}"
        )
    snapshot = capture_repository_snapshot(candidate)
    snapshot["repository_path"] = candidate.relative_to(root).as_posix() or "."
    _json(snapshot)
    if args.strict and (
        snapshot.get("status") != "captured"
        or not snapshot.get("worktree_clean")
    ):
        raise SystemExit(1)


def cmd_benchmark(args):
    root = _root(args)
    tasks = load_tasks(
        Path(args.tasks),
        require_research_protocol=bool(args.research_protocol),
    )
    result = run_benchmark(
        root,
        load_config(root),
        tasks,
        require_frozen_snapshot=bool(args.require_frozen_snapshot),
        require_research_protocol=bool(args.research_protocol),
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_benchmark_ablate(args):
    root = _root(args)
    tasks = load_tasks(
        Path(args.tasks),
        require_research_protocol=bool(args.research_protocol),
    )
    result = run_ablation_suite(
        root,
        load_config(root),
        tasks,
        args.profile or list(PROFILE_ORDER),
        require_frozen_snapshot=bool(args.require_frozen_snapshot),
        require_research_protocol=bool(args.research_protocol),
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_benchmark_algorithms(args):
    root = _root(args)
    tasks = load_tasks(
        Path(args.tasks),
        require_research_protocol=bool(args.research_protocol),
    )
    result = run_algorithm_ablation_suite(
        root,
        load_config(root),
        tasks,
        args.profile or list(ALGORITHM_PROFILE_ORDER),
        require_frozen_snapshot=bool(args.require_frozen_snapshot),
        require_research_protocol=bool(args.research_protocol),
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_benchmark_intervene(args):
    root = _root(args)
    tasks = load_tasks(
        Path(args.tasks),
        require_research_protocol=bool(args.research_protocol),
    )
    manifest = build_seed_intervention_manifest(
        root,
        load_config(root),
        tasks,
        args.mode or list(SEED_MODES),
        seed_k=args.seed_k,
        require_frozen_snapshot=bool(args.require_frozen_snapshot),
        require_research_protocol=bool(args.research_protocol),
    )
    if args.runner_command:
        command = [args.runner_command, *(args.runner_arg or [])]
        result = run_seed_interventions(
            root,
            manifest,
            command,
            timeout_seconds=args.runner_timeout,
            max_output_bytes=args.runner_max_output_bytes,
            env_allowlist=args.runner_env or [],
        )
    else:
        result = manifest
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def _load_json_object(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input report must be a JSON object")
    return data


def cmd_benchmark_statistics(args):
    result = analyze_seed_report(
        _load_json_object(args.input),
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
        stratify=args.stratify or [],
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_benchmark_calibrate(args):
    result = calibrate_sufficiency_threshold(
        _load_json_object(args.input),
        calibration_fraction=args.calibration_fraction,
        false_accept_cost=args.false_accept_cost,
        false_reject_cost=args.false_reject_cost,
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_benchmark_policy_advisor(args):
    result = build_safe_policy_advisor(
        _load_json_object(args.input),
        context_field=args.context_field,
        minimum_samples=args.minimum_samples,
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
        safety_margin=args.safety_margin,
        token_penalty=args.token_penalty,
        latency_penalty=args.latency_penalty,
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def _signing_key_from_env(name: str) -> bytes:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(
            f"policy signing key environment variable is empty: {name}"
        )
    return value.encode()


def cmd_learning_contextual_policy(args):
    root = _root(args)
    result = build_contextual_policy_report(
        root,
        context_fields=args.field or DEFAULT_POLICY_FIELDS,
        development_fraction=args.development_fraction,
        prior_weight=args.prior_weight,
        folds=args.folds,
        minimum_context_events=args.minimum_context_events,
        minimum_direct_exposures=args.minimum_direct_exposures,
        minimum_holdout_events=args.minimum_holdout_events,
        minimum_effective_sample_size=args.minimum_effective_sample_size,
        minimum_model_validation_events=(
            args.minimum_model_validation_events
        ),
        minimum_estimated_gain=args.minimum_estimated_gain,
        safety_margin=args.safety_margin,
        max_realized_cost=args.max_realized_cost,
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_learning_manifest(args):
    report = _load_json_object(args.input)
    manifest = create_policy_manifest(
        report,
        _signing_key_from_env(args.signing_key_env),
    )
    atomic_write_json(Path(args.output), manifest, sort_keys=True)
    _json({
        "created": True,
        "policy_id": manifest["policy_id"],
        "status": manifest["status"],
        "output": str(Path(args.output).resolve()),
    })


def cmd_learning_verify_manifest(args):
    manifest = _load_json_object(args.input)
    result = verify_policy_manifest(
        manifest,
        _signing_key_from_env(args.signing_key_env),
    )
    _json(result)
    if not result["valid"]:
        raise SystemExit(1)


def cmd_learning_shadow_evaluate(args):
    root = _root(args)
    manifest = _load_json_object(args.manifest)
    result = evaluate_shadow_policy(
        root,
        manifest,
        _signing_key_from_env(args.signing_key_env),
        confidence=args.confidence,
        reward_min=args.reward_min,
        reward_max=args.reward_max,
        max_importance_weight=args.max_importance_weight,
        minimum_new_events=args.minimum_new_events,
        safety_margin=args.safety_margin,
        max_realized_cost=args.max_realized_cost,
        bootstrap_resamples=args.resamples,
        bootstrap_seed=args.seed,
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def _deployment_state_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("deployment state path must stay inside project root")
    return resolved


def cmd_deployment_create(args):
    root = _root(args)
    signing_key = _signing_key_from_env(args.signing_key_env)
    state = create_deployment_state(
        root,
        _load_json_object(args.manifest),
        _load_json_object(args.shadow_report),
        signing_key,
        approved_by=args.approved_by,
        bounded_traffic_fraction=args.bounded_traffic,
        reward_min=args.reward_min,
        reward_max=args.reward_max,
        max_importance_weight=args.max_importance_weight,
        minimum_monitor_outcomes=args.minimum_monitor_outcomes,
        promotion_margin=args.promotion_margin,
        max_reward_regression=args.max_reward_regression,
        max_failure_rate=args.max_failure_rate,
        max_context_tv_distance=args.max_context_tv_distance,
        max_unknown_context_rate=args.max_unknown_context_rate,
        minimum_drift_samples=args.minimum_drift_samples,
        drift_window=args.drift_window,
        minimum_monitor_clusters=args.minimum_monitor_clusters,
        cluster_bootstrap_resamples=args.cluster_bootstrap_resamples,
        cluster_bootstrap_seed=args.cluster_bootstrap_seed,
        max_cumulative_realized_cost=args.max_cumulative_realized_cost,
    )
    path = _deployment_state_path(root, args.state)
    write_new_deployment_state(path, state, signing_key)
    mirror_learning_event(
        root,
        load_config(root),
        "deployment_state",
        state,
    )
    _json({
        "created": True,
        "policy_id": state["policy_id"],
        "stage": state["stage"],
        "generation": state["generation"],
        "traffic_fraction": state["traffic_fraction"],
        "state": path.relative_to(root).as_posix(),
    })


def cmd_deployment_status(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    verification = verify_deployment_state(
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    _json({
        **verification,
        "state": path.relative_to(root).as_posix(),
        "history_tail": (
            state.get("history", [])[-1]
            if isinstance(state.get("history"), list)
            and state.get("history")
            else None
        ),
        "guardrails": state.get("guardrails"),
    })
    if not verification["valid"]:
        raise SystemExit(1)


def cmd_deployment_guardrails(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    result = evaluate_live_guardrails(
        root,
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_deployment_promote(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    guardrail_report = (
        _load_json_object(args.guardrail_report)
        if args.guardrail_report
        else None
    )
    updated = update_deployment_state_file(
        path,
        _signing_key_from_env(args.signing_key_env),
        to_stage=args.to,
        actor=args.actor,
        expected_generation=args.expected_generation,
        guardrail_report=guardrail_report,
        reason=args.reason,
    )
    mirror_learning_event(
        root,
        load_config(root),
        "deployment_state",
        updated,
    )
    _json({
        "updated": True,
        "policy_id": updated["policy_id"],
        "stage": updated["stage"],
        "generation": updated["generation"],
        "traffic_fraction": updated["traffic_fraction"],
        "state": path.relative_to(root).as_posix(),
    })


def cmd_deployment_rollback(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    signing_key = _signing_key_from_env(args.signing_key_env)
    current = load_deployment_state(path)
    try:
        guardrail_report = evaluate_live_guardrails(
            root,
            current,
            signing_key,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        guardrail_report = {
            "scope": "manual-rollback-diagnostic-unavailable",
            "policy_id": current.get("policy_id"),
            "stage": current.get("stage"),
            "state_generation": current.get("generation"),
            "gate": {
                "rollback_required": True,
                "safe_to_advance": False,
                "rollback_blockers": ["manual_rollback"],
                "diagnostic_error": type(exc).__name__,
            },
        }
    updated = update_deployment_state_file(
        path,
        signing_key,
        to_stage="rolled_back",
        actor=args.actor,
        expected_generation=args.expected_generation,
        reason=args.reason,
    )
    config = load_config(root)
    mirror_learning_event(
        root,
        config,
        "deployment_state",
        updated,
    )
    incident_path = None
    deployment_cfg = (
        config.get("context", {}).get("deployment", {})
        if isinstance(config.get("context"), dict)
        else {}
    )
    if (
        isinstance(deployment_cfg, dict)
        and bool(deployment_cfg.get("incident_bundles", True))
    ):
        try:
            incident = create_incident_bundle(
                root,
                updated,
                guardrail_report,
                signing_key,
                reason=args.reason,
            )
            incident_path = write_incident_bundle(
                root,
                incident,
                signing_key,
            )
            mirror_learning_event(
                root,
                config,
                "deployment_incident",
                incident,
            )
        except (OSError, RuntimeError, ValueError):
            incident_path = None
    _json({
        "updated": True,
        "policy_id": updated["policy_id"],
        "stage": updated["stage"],
        "generation": updated["generation"],
        "traffic_fraction": updated["traffic_fraction"],
        "rollback": updated.get("rollback"),
        "incident_bundle": (
            Path(incident_path).relative_to(root.resolve()).as_posix()
            if incident_path is not None
            else None
        ),
        "state": path.relative_to(root).as_posix(),
    })


def cmd_deployment_metrics(args):
    root = _root(args)
    path = _deployment_state_path(root, args.state)
    state = load_deployment_state(path)
    report = evaluate_live_guardrails(
        root,
        state,
        _signing_key_from_env(args.signing_key_env),
    )
    payload = build_deployment_metrics(report)
    if args.output:
        write_deployment_metrics(Path(args.output), report)
    _json(payload)


def cmd_deployment_verify_incident(args):
    payload = _load_json_object(args.input)
    result = verify_incident_bundle(
        payload,
        _signing_key_from_env(args.signing_key_env),
    )
    _json(result)
    if not result["valid"]:
        raise SystemExit(1)


def cmd_production_status(args):
    root = _root(args)
    _json(production_store_status(root, load_config(root)))


def cmd_production_sync(args):
    root = _root(args)
    _json(sync_learning_store(root, load_config(root)))


def cmd_production_reconcile(args):
    root = _root(args)
    result = reconcile_learning_store(root, load_config(root))
    _json(result)
    if not result["consistent"]:
        raise SystemExit(1)


def cmd_learning_status(args):
    root = _root(args)
    _json(learning_status(root, load_config(root)))


def cmd_learning_record_outcome(args):
    root = _root(args)
    path = record_verified_outcome(
        root,
        args.decision_id,
        success=bool(args.success),
        source=args.source,
        reward=args.reward,
        realized_cost=args.realized_cost,
        config=load_config(root),
    )
    _json({
        "recorded": True,
        "decision_id": args.decision_id,
        "path": Path(path).relative_to(root.resolve()).as_posix(),
    })


def cmd_learning_evaluate(args):
    root = _root(args)
    result = evaluate_learning_policies(
        root,
        arms=args.arm or None,
        confidence=args.confidence,
        resamples=args.resamples,
        seed=args.seed,
        minimum_effective_sample_size=args.minimum_effective_sample_size,
        minimum_direct_exposures=args.minimum_direct_exposures,
        safety_margin=args.safety_margin,
        max_realized_cost=args.max_realized_cost,
    )
    if args.output:
        atomic_write_json(Path(args.output), result)
    _json(result)


def cmd_stats(args):
    root = _root(args)
    result = summarize_traces(root, args.limit)
    if args.recommend:
        result["policy_feedback"] = policy_recommendations(
            root,
            args.limit,
            args.minimum_runs,
        )
    _json(result)


def build_parser():
    p = argparse.ArgumentParser(
        prog="ai-workflow",
        description="AI Workflow Efficiency Control Plane",
    )
    p.add_argument("--root", help="project root; auto-detected by default")
    sp = p.add_subparsers(dest="command", required=True)

    q = sp.add_parser(
        "setup",
        help="connect AI Workflow to the current project; safe to rerun",
    )
    q.add_argument("--project-name")
    q.add_argument("--json", action="store_true", help="print machine-readable setup result")
    q.add_argument(
        "--create",
        action="store_true",
        help="explicitly create the project root when it does not exist",
    )
    q.add_argument(
        "--legacy-root-files",
        action="store_true",
        help="also create root AGENTS.md and .ai/PROJECT for legacy tools",
    )
    q.add_argument(
        "--no-discover-repos",
        action="store_true",
        help="skip read-only local Git repository discovery",
    )
    q.add_argument(
        "--discover-depth",
        type=int,
        default=3,
        help="maximum folder depth for multi-repo discovery",
    )
    idx = q.add_mutually_exclusive_group()
    idx.add_argument("--no-index", action="store_true", help="skip index construction during setup")
    idx.add_argument(
        "--full-index",
        action="store_true",
        help="force a full index rebuild instead of auto/incremental setup",
    )
    q.set_defaults(func=cmd_setup)

    q = sp.add_parser("bootstrap")
    q.add_argument("--project-name", required=True)
    q.set_defaults(func=cmd_bootstrap)

    q = sp.add_parser("init")
    q.add_argument("--project-name", required=True)
    q.set_defaults(func=cmd_init)

    q = sp.add_parser("route")
    q.add_argument("task")
    q.set_defaults(func=cmd_route)

    q = sp.add_parser("repos", help="review and manage discovered repositories")
    rsp = q.add_subparsers(dest="repos_command", required=True)

    r = rsp.add_parser("list", help="list discovered repositories and inclusion state")
    r.set_defaults(func=cmd_repos_list)

    r = rsp.add_parser(
        "refresh",
        help="rediscover repositories without automatically including new identities",
    )
    r.add_argument(
        "--discover-depth",
        type=int,
        help="override configured repository discovery depth",
    )
    r.set_defaults(func=cmd_repos_refresh)

    r = rsp.add_parser("include", help="explicitly include one discovered repository")
    r.add_argument("repository", help="relative path, repository ID, remote identity, or unique name")
    r.set_defaults(func=cmd_repos_include)

    r = rsp.add_parser("exclude", help="exclude one discovered repository")
    r.add_argument("repository", help="relative path, repository ID, remote identity, or unique name")
    r.set_defaults(func=cmd_repos_exclude)

    for name, fn in (("brief", cmd_brief), ("context", cmd_context)):
        q = sp.add_parser(name)
        q.add_argument("task")
        q.add_argument("--symbol")
        q.add_argument("--endpoint")
        q.add_argument("--changed-file", action="append", default=[])
        q.add_argument("--trace", action="store_true")
        if name == "brief":
            q.add_argument("--write-handoff", action="store_true")
            q.add_argument(
                "--format",
                choices=["json", "markdown", "prompt"],
                default="json",
            )
        q.set_defaults(func=fn)

    q = sp.add_parser("index")
    q.add_argument("--incremental", action="store_true")
    q.add_argument(
        "--strict-hash",
        "--verify-hashes",
        dest="strict_hash",
        action="store_true",
        help="hash all source files when verifying an incremental index",
    )
    q.set_defaults(func=cmd_index)

    q = sp.add_parser("doctor")
    q.add_argument("--strict", action="store_true")
    q.set_defaults(func=cmd_doctor)

    q = sp.add_parser("verify")
    q.add_argument("--check", action="append", default=[])
    q.add_argument("--strict", action="store_true")
    q.set_defaults(func=cmd_verify)

    q = sp.add_parser(
        "benchmark-corpus",
        help="author and validate research-grade benchmark corpus v2 data",
    )
    bcsp = q.add_subparsers(dest="benchmark_corpus_command", required=True)

    bc = bcsp.add_parser(
        "validate",
        help="validate corpus-v2 schema and report publication readiness",
    )
    bc.add_argument("--input", required=True)
    bc.add_argument(
        "--require-ready",
        action="store_true",
        help="exit nonzero unless the corpus clears the research-scale floor",
    )
    bc.set_defaults(func=cmd_benchmark_corpus_validate)

    bc = bcsp.add_parser(
        "snapshot",
        help="capture Git HEAD, cleanliness, and tracked-tree manifest",
    )
    bc.add_argument("--repository", default=".")
    bc.add_argument(
        "--strict",
        action="store_true",
        help="exit nonzero unless the repository is clean and capturable",
    )
    bc.set_defaults(func=cmd_benchmark_corpus_snapshot)

    q = sp.add_parser("benchmark")
    q.add_argument("--tasks", required=True)
    q.add_argument("--output")
    q.add_argument(
        "--research-protocol",
        action="store_true",
        help=(
            "require research task types, file/span gold labels, clean "
            "frozen contents, and selective-control provenance"
        ),
    )
    q.add_argument(
        "--require-frozen-snapshot",
        action="store_true",
        help=(
            "fail unless declared base commit, clean worktree, and optional "
            "content manifest all match"
        ),
    )
    q.set_defaults(func=cmd_benchmark)

    q = sp.add_parser(
        "benchmark-ablate",
        help="compare retrieval provider families on the same frozen benchmark cases",
    )
    q.add_argument("--tasks", required=True)
    q.add_argument("--output")
    q.add_argument(
        "--profile",
        action="append",
        choices=list(PROFILE_ORDER),
        help="profile to run; repeat to compare a subset (defaults to all)",
    )
    q.add_argument("--research-protocol", action="store_true")
    q.add_argument("--require-frozen-snapshot", action="store_true")
    q.set_defaults(func=cmd_benchmark_ablate)

    q = sp.add_parser(
        "benchmark-algorithms",
        help="compare retrieval ranking, selection, budget, and sufficiency algorithms",
    )
    q.add_argument("--tasks", required=True)
    q.add_argument("--output")
    q.add_argument(
        "--profile",
        action="append",
        choices=list(ALGORITHM_PROFILE_ORDER),
        help="profile to run; repeat to compare a subset (defaults to all)",
    )
    q.add_argument("--research-protocol", action="store_true")
    q.add_argument("--require-frozen-snapshot", action="store_true")
    q.set_defaults(func=cmd_benchmark_algorithms)

    q = sp.add_parser(
        "benchmark-intervene",
        help="build or execute retrieval/random/oracle seed interventions",
    )
    q.add_argument("--tasks", required=True)
    q.add_argument("--output")
    q.add_argument(
        "--mode",
        action="append",
        choices=list(SEED_MODES),
        help="seed mode; repeat to compare a subset (defaults to all)",
    )
    q.add_argument("--seed-k", type=int, default=5)
    q.add_argument("--research-protocol", action="store_true")
    q.add_argument("--require-frozen-snapshot", action="store_true")
    q.add_argument(
        "--runner-command",
        help="optional executable implementing the JSON intervention runner protocol",
    )
    q.add_argument(
        "--runner-arg",
        action="append",
        default=[],
        help="argument passed to the runner executable; repeat as needed",
    )
    q.add_argument(
        "--runner-timeout",
        type=float,
        default=120.0,
        help="per-intervention runner timeout in seconds",
    )
    q.add_argument(
        "--runner-max-output-bytes",
        type=int,
        default=4 * 1024 * 1024,
        help="maximum accepted stdout bytes per runner invocation",
    )
    q.add_argument(
        "--runner-env",
        action="append",
        default=[],
        help="environment variable name explicitly exposed to the runner",
    )
    q.set_defaults(func=cmd_benchmark_intervene)

    q = sp.add_parser(
        "benchmark-statistics",
        help="add paired bootstrap confidence intervals to seed interventions",
    )
    q.add_argument("--input", required=True)
    q.add_argument("--output")
    q.add_argument("--confidence", type=float, default=0.95)
    q.add_argument("--resamples", type=int, default=5000)
    q.add_argument("--seed", type=int, default=20260911)
    q.add_argument(
        "--stratify",
        action="append",
        default=[],
        help="result field to analyze separately; repeat as needed",
    )
    q.set_defaults(func=cmd_benchmark_statistics)

    q = sp.add_parser(
        "benchmark-calibrate",
        help="calibrate an advisory sufficiency threshold on a held-out split",
    )
    q.add_argument("--input", required=True)
    q.add_argument("--output")
    q.add_argument("--calibration-fraction", type=float, default=0.7)
    q.add_argument("--false-accept-cost", type=float, default=5.0)
    q.add_argument("--false-reject-cost", type=float, default=1.0)
    q.set_defaults(func=cmd_benchmark_calibrate)

    q = sp.add_parser(
        "benchmark-policy-advisor",
        help="derive high-confidence advisory retrieval policies from ablations",
    )
    q.add_argument("--input", required=True)
    q.add_argument("--output")
    q.add_argument("--context-field", default="task_type")
    q.add_argument("--minimum-samples", type=int, default=10)
    q.add_argument("--confidence", type=float, default=0.95)
    q.add_argument("--resamples", type=int, default=5000)
    q.add_argument("--seed", type=int, default=20260911)
    q.add_argument("--safety-margin", type=float, default=0.0)
    q.add_argument("--token-penalty", type=float, default=0.05)
    q.add_argument("--latency-penalty", type=float, default=0.01)
    q.set_defaults(func=cmd_benchmark_policy_advisor)

    q = sp.add_parser(
        "learning",
        help="inspect and evaluate the opt-in safe retrieval learning layer",
    )
    lsp = q.add_subparsers(dest="learning_command", required=True)

    l = lsp.add_parser("status", help="show learning mode, safety locks, and record counts")
    l.set_defaults(func=cmd_learning_status)

    l = lsp.add_parser(
        "record-outcome",
        help="attach a delayed verified outcome to one logged retrieval decision",
    )
    l.add_argument("decision_id")
    outcome = l.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--success", action="store_true")
    outcome.add_argument("--failure", action="store_true")
    l.add_argument("--source", required=True)
    l.add_argument("--reward", type=float)
    l.add_argument("--realized-cost", type=float, default=0.0)
    l.set_defaults(func=cmd_learning_record_outcome)

    l = lsp.add_parser(
        "contextual-policy",
        help="develop and holdout-evaluate a contextual retrieval policy",
    )
    l.add_argument(
        "--field",
        action="append",
        choices=list(FEATURE_FIELDS),
        help="context feature used by the policy; repeat as needed",
    )
    l.add_argument("--development-fraction", type=float, default=0.7)
    l.add_argument("--prior-weight", type=float, default=5.0)
    l.add_argument("--folds", type=int, default=5)
    l.add_argument("--minimum-context-events", type=int, default=10)
    l.add_argument("--minimum-direct-exposures", type=int, default=3)
    l.add_argument("--minimum-holdout-events", type=int, default=20)
    l.add_argument(
        "--minimum-effective-sample-size",
        type=float,
        default=10.0,
    )
    l.add_argument(
        "--minimum-model-validation-events",
        type=int,
        default=10,
    )
    l.add_argument("--minimum-estimated-gain", type=float, default=0.0)
    l.add_argument("--safety-margin", type=float, default=0.0)
    l.add_argument("--max-realized-cost", type=float)
    l.add_argument("--confidence", type=float, default=0.95)
    l.add_argument("--resamples", type=int, default=5000)
    l.add_argument("--seed", type=int, default=20260911)
    l.add_argument("--output")
    l.set_defaults(func=cmd_learning_contextual_policy)

    l = lsp.add_parser(
        "create-manifest",
        help="create an HMAC-signed shadow-only policy manifest",
    )
    l.add_argument("--input", required=True)
    l.add_argument("--output", required=True)
    l.add_argument("--signing-key-env", required=True)
    l.set_defaults(func=cmd_learning_manifest)

    l = lsp.add_parser(
        "verify-manifest",
        help="verify policy manifest integrity and safety invariants",
    )
    l.add_argument("--input", required=True)
    l.add_argument("--signing-key-env", required=True)
    l.set_defaults(func=cmd_learning_verify_manifest)

    l = lsp.add_parser(
        "shadow-evaluate",
        help=(
            "evaluate a fixed signed policy only on verified outcomes "
            "recorded after its evidence cutoff"
        ),
    )
    l.add_argument("--manifest", required=True)
    l.add_argument("--signing-key-env", required=True)
    l.add_argument("--confidence", type=float, default=0.95)
    l.add_argument("--reward-min", type=float, default=0.0)
    l.add_argument("--reward-max", type=float, default=1.0)
    l.add_argument("--max-importance-weight", type=float, default=20.0)
    l.add_argument("--minimum-new-events", type=int, default=20)
    l.add_argument("--safety-margin", type=float, default=0.0)
    l.add_argument("--max-realized-cost", type=float)
    l.add_argument("--resamples", type=int, default=5000)
    l.add_argument("--seed", type=int, default=20260911)
    l.add_argument("--output")
    l.set_defaults(func=cmd_learning_shadow_evaluate)

    l = lsp.add_parser(
        "evaluate",
        help="run propensity-aware IPS/SNIPS evaluation and conservative promotion gates",
    )
    l.add_argument(
        "--arm",
        action="append",
        choices=list(SAFE_EXPLORATION_ARMS),
        help="target retrieval arm; repeat to evaluate a subset",
    )
    l.add_argument("--confidence", type=float, default=0.95)
    l.add_argument("--resamples", type=int, default=5000)
    l.add_argument("--seed", type=int, default=20260911)
    l.add_argument("--minimum-effective-sample-size", type=float, default=10.0)
    l.add_argument("--minimum-direct-exposures", type=int, default=5)
    l.add_argument("--safety-margin", type=float, default=0.0)
    l.add_argument("--max-realized-cost", type=float)
    l.add_argument("--output")
    l.set_defaults(func=cmd_learning_evaluate)

    q = sp.add_parser(
        "deployment",
        help="manage signed staged rollout of a contextual retrieval policy",
    )
    dsp = q.add_subparsers(dest="deployment_command", required=True)
    default_state = (
        "ai-workspace/generated/learning/deployment/active.json"
    )

    d = dsp.add_parser(
        "create",
        help="approve signed shadow evidence and create a zero-traffic state",
    )
    d.add_argument("--manifest", required=True)
    d.add_argument("--shadow-report", required=True)
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.add_argument("--approved-by", required=True)
    d.add_argument("--bounded-traffic", type=float, default=0.25)
    d.add_argument("--reward-min", type=float, default=0.0)
    d.add_argument("--reward-max", type=float, default=1.0)
    d.add_argument("--max-importance-weight", type=float, default=100.0)
    d.add_argument("--minimum-monitor-outcomes", type=int, default=20)
    d.add_argument("--promotion-margin", type=float, default=0.0)
    d.add_argument("--max-reward-regression", type=float, default=0.05)
    d.add_argument("--max-failure-rate", type=float, default=0.10)
    d.add_argument("--max-context-tv-distance", type=float, default=0.30)
    d.add_argument("--max-unknown-context-rate", type=float, default=0.20)
    d.add_argument("--minimum-drift-samples", type=int, default=50)
    d.add_argument("--drift-window", type=int, default=200)
    d.add_argument("--minimum-monitor-clusters", type=int, default=5)
    d.add_argument("--cluster-bootstrap-resamples", type=int, default=2000)
    d.add_argument("--cluster-bootstrap-seed", type=int, default=20260911)
    d.add_argument("--max-cumulative-realized-cost", type=float)
    d.set_defaults(func=cmd_deployment_create)

    d = dsp.add_parser("status", help="verify and inspect deployment state")
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.set_defaults(func=cmd_deployment_status)

    d = dsp.add_parser(
        "guardrails",
        help="evaluate cumulative live canary safety and drift signals",
    )
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.add_argument("--output")
    d.set_defaults(func=cmd_deployment_guardrails)

    d = dsp.add_parser(
        "promote",
        help="manually advance one rollout stage after required evidence",
    )
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.add_argument(
        "--to",
        required=True,
        choices=["canary_1", "canary_5", "canary_10", "bounded"],
    )
    d.add_argument("--actor", required=True)
    d.add_argument("--expected-generation", type=int, required=True)
    d.add_argument("--guardrail-report")
    d.add_argument("--reason")
    d.set_defaults(func=cmd_deployment_promote)

    d = dsp.add_parser(
        "metrics",
        help="export low-cardinality deployment metrics from live evidence",
    )
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.add_argument("--output")
    d.set_defaults(func=cmd_deployment_metrics)

    d = dsp.add_parser(
        "verify-incident",
        help="verify a signed Stage-8 deployment incident bundle",
    )
    d.add_argument("--input", required=True)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.set_defaults(func=cmd_deployment_verify_incident)

    d = dsp.add_parser(
        "rollback",
        help="manually terminate canary traffic and return to adaptive_math",
    )
    d.add_argument("--state", default=default_state)
    d.add_argument(
        "--signing-key-env",
        default="AI_WORKFLOW_POLICY_SIGNING_KEY",
    )
    d.add_argument("--actor", required=True)
    d.add_argument("--expected-generation", type=int, required=True)
    d.add_argument("--reason", required=True)
    d.set_defaults(func=cmd_deployment_rollback)

    q = sp.add_parser(
        "production",
        help="manage the Stage-8 same-host WAL evidence mirror",
    )
    psp = q.add_subparsers(dest="production_command", required=True)
    x = psp.add_parser("status", help="inspect SQLite WAL store health")
    x.set_defaults(func=cmd_production_status)
    x = psp.add_parser(
        "sync",
        help="idempotently backfill immutable learning records into SQLite",
    )
    x.set_defaults(func=cmd_production_sync)
    x = psp.add_parser(
        "reconcile",
        help="verify SQLite learning-event digests against canonical files",
    )
    x.set_defaults(func=cmd_production_reconcile)

    q = sp.add_parser("stats")
    q.add_argument("--limit", type=int, default=200)
    q.add_argument("--recommend", action="store_true")
    q.add_argument("--minimum-runs", type=int, default=20)
    q.set_defaults(func=cmd_stats)

    q = sp.add_parser("handoff")
    q.add_argument("action", choices=["validate"])
    q.set_defaults(func=cmd_handoff)

    q = sp.add_parser("memory")
    msp = q.add_subparsers(dest="memory_command", required=True)
    m = msp.add_parser("add")
    m.add_argument("--type", required=True)
    m.add_argument("--keywords", required=True)
    m.add_argument("--summary", required=True)
    m.add_argument("--evidence")
    m.add_argument("--file", action="append")
    m.add_argument("--confidence", type=float, default=0.8)
    m.set_defaults(func=cmd_memory_add)
    m = msp.add_parser("search")
    m.add_argument("query")
    m.add_argument("--limit", type=int)
    m.set_defaults(func=cmd_memory_search)
    m = msp.add_parser("list")
    m.set_defaults(func=cmd_memory_list)
    m = msp.add_parser("prune")
    m.set_defaults(func=cmd_memory_prune)
    m = msp.add_parser("export")
    m.add_argument("--format", choices=["jsonl"], default="jsonl")
    m.add_argument("--output", required=True)
    m.set_defaults(func=cmd_memory_export)

    q = sp.add_parser("compress")
    q.add_argument("--file")
    q.add_argument("--max-lines", type=int, default=80)
    q.add_argument("--max-chars", type=int, default=12000)
    q.set_defaults(func=cmd_compress)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)
