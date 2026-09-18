from __future__ import annotations

from pathlib import Path
from ..benchmark import load_tasks, run_benchmark
from ..benchmark_corpus import (
    corpus_summary,
    load_corpus_document,
)
from ..benchmark_ablation import PROFILE_ORDER, run_ablation_suite
from ..benchmark_algorithm_ablation import (
    ALGORITHM_PROFILE_ORDER,
    run_algorithm_ablation_suite,
)
from ..benchmark_intervention import (
    SEED_MODES,
    build_seed_intervention_manifest,
    run_seed_interventions,
)
from ..benchmark_calibration import calibrate_sufficiency_threshold
from ..benchmark_policy_advisor import build_safe_policy_advisor
from ..benchmark_protocol import capture_repository_snapshot
from ..benchmark_statistics import analyze_seed_report
from ..config import estimate_tokens, find_project_root, load_config
from ..io_utils import atomic_write_json, atomic_write_text

from .common import _json, _root

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
