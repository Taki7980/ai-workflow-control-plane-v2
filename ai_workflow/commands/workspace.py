from __future__ import annotations

import json
import sys
from pathlib import Path
from ..bootstrap import WORKSPACE_AGENTS_RELATIVE, WORKSPACE_PROJECT_RELATIVE, bootstrap, setup
from ..budget import budget_for
from ..classifier import classify
from ..compress import compress_text
from ..config import estimate_tokens, load_config
from ..doctor import run as doctor_run
from ..handoff import handoff_path, render as render_handoff, validate as validate_handoff
from ..indexer import index_workspace
from ..io_utils import atomic_write_json, atomic_write_text
from ..repository_registry import refresh_registry, registry_summary, set_repository_included
from ..provider import detect, execution_provider, model_tier
from ..retrieval import detect_changed_files, gather_detailed
from ..state import policy_recommendations, summarize_traces
from ..verify import verify

from .common import _json, _root

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
        discovery_depth=int(getattr(args, "discover_depth", 8)),
        sync_crg=not bool(getattr(args, "no_crg_sync", False)),
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
    if registry.get("status") in {"created", "refreshed"}:
        print(
            "Repositories: "
            f"{registry.get('discovered', 0)} discovered; "
            f"{registry.get('accepted', 0)} active"
        )
    crg = result.get("code_review_graph") or {}
    if crg.get("installed"):
        print(
            "Code Review Graph: "
            f"{crg.get('ready', 0)}/{crg.get('attempted', 0)} repositories ready "
            f"under ai-workspace/code-review-graph"
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
            "index": index_workspace(
                root,
                load_config(root),
                mode="full",
            ),
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
        result = refresh_registry(
            root,
            max_depth=depth,
            config=config,
            auto_include=False,
        )
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
    _json(
        index_workspace(
            root,
            load_config(root),
            mode=(
                "incremental"
                if getattr(args, "incremental", False)
                else "full"
            ),
            strict_hash=bool(getattr(args, "strict_hash", False)),
        )
    )

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
