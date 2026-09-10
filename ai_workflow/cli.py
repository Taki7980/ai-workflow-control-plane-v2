from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adaptive_broker import gather_detailed
from .benchmark import load_tasks, run_benchmark
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
from .bootstrap import WORKSPACE_AGENTS_RELATIVE, WORKSPACE_PROJECT_RELATIVE, bootstrap, setup
from .budget import budget_for
from .classifier import classify
from .compress import compress_text
from .config import estimate_tokens, find_project_root, load_config
from .context_broker import detect_changed_files
from .doctor import run as doctor_run
from .handoff import handoff_path, render as render_handoff, validate as validate_handoff
from .indexer import build_indexes, incremental_indexes
from .io_utils import atomic_write_json, atomic_write_text
from .memory import add_memory, export_memory_jsonl, list_memories, prune_stale, search_memory
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

    q = sp.add_parser("benchmark")
    q.add_argument("--tasks", required=True)
    q.add_argument("--output")
    q.add_argument(
        "--research-protocol",
        action="store_true",
        help=(
            "require Agent Retrieval Bench-style task types, file-level gold "
            "labels, frozen base commits, and selective-control metadata"
        ),
    )
    q.add_argument(
        "--require-frozen-snapshot",
        action="store_true",
        help="fail if any declared benchmark base_commit differs from the local checkout",
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
