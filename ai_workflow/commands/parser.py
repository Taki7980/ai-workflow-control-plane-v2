from __future__ import annotations

import argparse

from ..contextual_features import FEATURE_FIELDS
from ..evaluation import ALGORITHM_PROFILE_ORDER, PROFILE_ORDER, SEED_MODES
from ..retrieval_learning import SAFE_EXPLORATION_ARMS
from .deployment import (
    cmd_deployment_create,
    cmd_deployment_guardrails,
    cmd_deployment_metrics,
    cmd_deployment_promote,
    cmd_deployment_rollback,
    cmd_deployment_status,
    cmd_deployment_verify_incident,
)
from .evaluation import (
    cmd_benchmark,
    cmd_benchmark_ablate,
    cmd_benchmark_algorithms,
    cmd_benchmark_calibrate,
    cmd_benchmark_corpus_snapshot,
    cmd_benchmark_corpus_validate,
    cmd_benchmark_intervene,
    cmd_benchmark_policy_advisor,
    cmd_benchmark_statistics,
)
from .learning import (
    cmd_learning_contextual_policy,
    cmd_learning_evaluate,
    cmd_learning_manifest,
    cmd_learning_record_outcome,
    cmd_learning_shadow_evaluate,
    cmd_learning_status,
    cmd_learning_verify_manifest,
)
from .memory import (
    cmd_memory_add,
    cmd_memory_export,
    cmd_memory_list,
    cmd_memory_prune,
    cmd_memory_search,
)
from .production import (
    cmd_production_reconcile,
    cmd_production_status,
    cmd_production_sync,
)
from .workspace import (
    cmd_bootstrap,
    cmd_brief,
    cmd_compress,
    cmd_context,
    cmd_doctor,
    cmd_handoff,
    cmd_index,
    cmd_init,
    cmd_repos_exclude,
    cmd_repos_include,
    cmd_repos_list,
    cmd_repos_refresh,
    cmd_route,
    cmd_setup,
    cmd_stats,
    cmd_verify,
)

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
        default=8,
        help="maximum folder depth for recursive multi-repo discovery",
    )
    q.add_argument(
        "--no-crg-sync",
        action="store_true",
        help="skip automatic Code Review Graph build/update during setup",
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
        help="rediscover repositories without changing explicit activation decisions",
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
    l.add_argument("--verifier-identity", required=True)
    l.add_argument("--evidence-digest", required=True)
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
