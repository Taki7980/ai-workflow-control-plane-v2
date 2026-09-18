from __future__ import annotations

from pathlib import Path
from ..config import estimate_tokens, find_project_root, load_config
from ..contextual_features import DEFAULT_POLICY_FIELDS, FEATURE_FIELDS
from ..contextual_policy import build_contextual_policy_report
from ..io_utils import atomic_write_json, atomic_write_text
from ..learning_ope import evaluate_learning_policies
from ..policy_manifest import (
    create_policy_manifest,
    verify_policy_manifest,
)
from ..retrieval_learning import (
    SAFE_EXPLORATION_ARMS,
    learning_status,
    record_verified_outcome,
)
from ..shadow_policy import evaluate_shadow_policy

from .common import _json, _load_json_object, _root, _signing_key_from_env

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
        verifier_identity=args.verifier_identity,
        evidence_digest=args.evidence_digest,
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
