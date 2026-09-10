from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .adaptive_broker import gather_detailed
from .benchmark import load_tasks, run_benchmark
from .bootstrap import bootstrap, setup
from .budget import budget_for
from .classifier import classify
from .compress import compress_text
from .config import find_project_root, load_config, estimate_tokens
from .context_broker import detect_changed_files
from .doctor import run as doctor_run
from .handoff import validate as validate_handoff, render as render_handoff
from .indexer import build_indexes, incremental_indexes
from .memory import add_memory, search_memory, list_memories, prune_stale, export_memory_jsonl
from .providers import detect, execution_provider, model_tier
from .telemetry import policy_recommendations, summarize_traces
from .verify import verify


def _root(args) -> Path:
    return Path(args.root).resolve() if getattr(args, "root", None) else find_project_root()
def _json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

def cmd_setup(args):
    result = setup(_root(args), args.project_name)
    if args.json:
        _json(result)
        return
    print(f"AI Workflow ready: {result['project']}")
    print(f"Root: {result['root']}")
    if result["created"]:
        print("Created: " + ", ".join(result["created"]))
    if result["preserved"]:
        print("Preserved: " + ", ".join(result["preserved"]))
    print("Next: " + result["next"])

def cmd_bootstrap(args):
    try: _json(bootstrap(_root(args), args.project_name))
    except FileExistsError as exc: raise SystemExit(str(exc)) from exc

def cmd_init(args):
    root = _root(args); agents = root / "AGENTS.md"
    try:
        load_config(root); text = agents.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", args.project_name)
    except FileNotFoundError as exc:
        raise SystemExit("Copy the workflow template into the project or run `ai-workflow bootstrap --project-name NAME`; config and AGENTS.md are required.") from exc
    (root / ".ai").mkdir(parents=True, exist_ok=True)
    (root / ".ai" / "PROJECT").write_text(str(root) + "\n", encoding="utf-8")
    agents.write_text(text, encoding="utf-8")
    _json({"status": "initialized", "project": args.project_name, "root": str(root), "index": build_indexes(root)})

def _decision(root: Path, task: str):
    config = load_config(root); providers = detect(root, config); decision = classify(task, config); budget = budget_for(decision.lane, config)
    provider = execution_provider(decision.lane, config, providers)
    return config, providers, decision, budget, provider, model_tier(decision, config)

def cmd_route(args):
    root = _root(args); config, providers, decision, budget, provider, model = _decision(root, args.task)
    _json({**decision.to_dict(), "execution_provider": provider, "model_tier": model, "providers": providers.to_dict(), "budget": {"estimated_context_tokens": budget.estimated_tokens, "max_output_tokens": budget.output_tokens}})

def _resolve_changed(root: Path, explicit: list[str]) -> list[str]:
    return explicit if explicit else detect_changed_files(root)

def _format_brief(packet: dict, fmt: str) -> str:
    if fmt == "json": return json.dumps(packet, indent=2, ensure_ascii=False)
    retrieval = packet.get("retrieval", {}) or {}; orchestration = retrieval.get("orchestration", {}) or {}
    skills = orchestration.get("superpowers_skills", []) or []; crg_plan = orchestration.get("crg_plan", []) or []
    evidence = retrieval.get("evidence_state", "unknown"); fingerprint = (retrieval.get("workspace_state") or {}).get("fingerprint", "unknown")
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
            "", "## Context", "", ctx_text or "(no context gathered)",
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
    if packet.get("context"): lines += ["[CONTEXT_START]", ctx_text, "[CONTEXT_END]"]
    lines.append(f"[INVARIANTS] {packet.get('invariants', 'preserve existing contracts unless task explicitly changes them')}")
    return "\n".join(lines)

def cmd_brief(args):
    root = _root(args); config, providers, decision, budget, provider, model = _decision(root, args.task); changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(root, args.task, decision, budget, config, providers, args.symbol, args.endpoint, changed, write_telemetry=(decision.lane.value != "answer" or args.trace))
    packet = {"task": args.task, **decision.to_dict(), "execution_provider": provider, "model_tier": model,
        "execution_hint": ("Follow the emitted Superpowers skill sequence and CRG plan; do not edit while evidence_state=requires_exploration."
            if provider == "superpowers" else "Use native lightweight execution." if decision.lane.value == "small" else
            "Use native Plan -> Build -> Review fallback." if decision.lane.value == "full" else "Answer directly; no implementation workflow."),
        "budget": {"estimated_context_tokens": budget.estimated_tokens, "max_output_tokens": budget.output_tokens}, "retrieval": retrieval,
        "context": [i.to_dict() for i in items], "estimated_context_tokens_used": estimate_tokens("\n".join(i.text for i in items)),
        "output_compression": "rtk" if providers.rtk else "builtin", "changed_files_detected": changed}
    if args.write_handoff and decision.lane.value != "answer":
        text = render_handoff(decision, provider, [i.source for i in items], args.task); (root / ".ai").mkdir(parents=True, exist_ok=True)
        (root / ".ai" / "HANDOFF.md").write_text(text, encoding="utf-8"); packet["handoff_written"] = ".ai/HANDOFF.md"
    if decision.lane.value != "answer":
        out = root / "ai-workspace" / "generated" / "last-brief.json"; out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(_format_brief(packet, getattr(args, "format", "json")))

def cmd_context(args):
    root = _root(args); config, providers, decision, budget, _, _ = _decision(root, args.task); changed = _resolve_changed(root, args.changed_file)
    items, retrieval = gather_detailed(root, args.task, decision, budget, config, providers, args.symbol, args.endpoint, changed, write_telemetry=args.trace)
    _json({"lane": decision.lane.value, "risk": decision.risk.value, "confidence": decision.confidence, "budget": budget.estimated_tokens, "retrieval": retrieval, "items": [i.to_dict() for i in items], "estimated_tokens": estimate_tokens("\n".join(i.text for i in items))})

def cmd_index(args): _json(incremental_indexes(_root(args)) if getattr(args, "incremental", False) else build_indexes(_root(args)))
def cmd_doctor(args):
    root=_root(args); result,ok=doctor_run(root,load_config(root)); _json(result)
    if args.strict and not ok: raise SystemExit(1)
def cmd_handoff(args):
    root=_root(args); errors=validate_handoff(root,int(load_config(root)["handoff"].get("max_lines",30))); _json({"valid":not errors,"errors":errors})
    if errors: raise SystemExit(1)
def cmd_memory_add(args): _json(add_memory(_root(args),args.type,args.keywords,args.summary,args.evidence or "",args.file or [],args.confidence))
def cmd_memory_search(args):
    root=_root(args); cfg=load_config(root); _json(search_memory(root,args.query,args.limit or int(cfg["memory"]["max_results"]),float(cfg["memory"].get("minimum_confidence",0.55))))
def cmd_memory_list(args): _json(list_memories(_root(args)))
def cmd_memory_prune(args): _json(prune_stale(_root(args)))
def cmd_memory_export(args):
    destination = Path(args.output).resolve()
    count = export_memory_jsonl(_root(args), destination)
    _json({"format": "jsonl", "output": str(destination), "records": count})
def cmd_compress(args):
    text=Path(args.file).read_text(encoding="utf-8",errors="replace") if args.file else sys.stdin.read(); sys.stdout.write(compress_text(text,args.max_lines,args.max_chars))
def cmd_verify(args):
    root=_root(args); cfg=load_config(root); result=verify(root,args.check or [],int(cfg["handoff"].get("max_lines",30))); _json(result)
    if args.strict and not result["ok"]: raise SystemExit(1)
def cmd_benchmark(args):
    root=_root(args); result=run_benchmark(root,load_config(root),load_tasks(Path(args.tasks)))
    if args.output: Path(args.output).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    _json(result)
def cmd_stats(args):
    root=_root(args); result=summarize_traces(root,args.limit)
    if args.recommend: result["policy_feedback"]=policy_recommendations(root,args.limit,args.minimum_runs)
    _json(result)

def build_parser():
    p=argparse.ArgumentParser(prog="ai-workflow",description="AI Workflow Efficiency Control Plane"); p.add_argument("--root",help="project root; auto-detected by default"); sp=p.add_subparsers(dest="command",required=True)
    q=sp.add_parser("setup",help="connect AI Workflow to the current project; safe to rerun"); q.add_argument("--project-name"); q.add_argument("--json",action="store_true",help="print machine-readable setup result"); q.set_defaults(func=cmd_setup)
    q=sp.add_parser("bootstrap"); q.add_argument("--project-name",required=True); q.set_defaults(func=cmd_bootstrap)
    q=sp.add_parser("init"); q.add_argument("--project-name",required=True); q.set_defaults(func=cmd_init)
    q=sp.add_parser("route"); q.add_argument("task"); q.set_defaults(func=cmd_route)
    for name,fn in (("brief",cmd_brief),("context",cmd_context)):
        q=sp.add_parser(name); q.add_argument("task"); q.add_argument("--symbol"); q.add_argument("--endpoint"); q.add_argument("--changed-file",action="append",default=[]); q.add_argument("--trace",action="store_true")
        if name=="brief": q.add_argument("--write-handoff",action="store_true"); q.add_argument("--format",choices=["json","markdown","prompt"],default="json")
        q.set_defaults(func=fn)
    q=sp.add_parser("index"); q.add_argument("--incremental",action="store_true"); q.set_defaults(func=cmd_index)
    q=sp.add_parser("doctor"); q.add_argument("--strict",action="store_true"); q.set_defaults(func=cmd_doctor)
    q=sp.add_parser("verify"); q.add_argument("--check",action="append",default=[]); q.add_argument("--strict",action="store_true"); q.set_defaults(func=cmd_verify)
    q=sp.add_parser("benchmark"); q.add_argument("--tasks",required=True); q.add_argument("--output"); q.set_defaults(func=cmd_benchmark)
    q=sp.add_parser("stats"); q.add_argument("--limit",type=int,default=200); q.add_argument("--recommend",action="store_true"); q.add_argument("--minimum-runs",type=int,default=20); q.set_defaults(func=cmd_stats)
    q=sp.add_parser("handoff"); q.add_argument("action",choices=["validate"]); q.set_defaults(func=cmd_handoff)
    q=sp.add_parser("memory"); msp=q.add_subparsers(dest="memory_command",required=True)
    m=msp.add_parser("add"); m.add_argument("--type",required=True); m.add_argument("--keywords",required=True); m.add_argument("--summary",required=True); m.add_argument("--evidence"); m.add_argument("--file",action="append"); m.add_argument("--confidence",type=float,default=0.8); m.set_defaults(func=cmd_memory_add)
    m=msp.add_parser("search"); m.add_argument("query"); m.add_argument("--limit",type=int); m.set_defaults(func=cmd_memory_search)
    m=msp.add_parser("list"); m.set_defaults(func=cmd_memory_list); m=msp.add_parser("prune"); m.set_defaults(func=cmd_memory_prune)
    m=msp.add_parser("export"); m.add_argument("--format",choices=["jsonl"],default="jsonl"); m.add_argument("--output",required=True); m.set_defaults(func=cmd_memory_export)
    q=sp.add_parser("compress"); q.add_argument("--file"); q.add_argument("--max-lines",type=int,default=80); q.add_argument("--max-chars",type=int,default=12000); q.set_defaults(func=cmd_compress)
    return p

def main():
    args=build_parser().parse_args(); args.func(args)
