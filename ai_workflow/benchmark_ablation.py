from __future__ import annotations

import copy
from typing import Any

from .benchmark import run_benchmark


PROFILE_ORDER = (
    "adaptive",
    "base_only",
    "base_semantic",
    "base_structural",
)


def profile_config(config: dict[str, Any], profile: str) -> dict[str, Any]:
    name = str(profile).strip().lower()
    if name not in PROFILE_ORDER:
        raise ValueError(
            f"unknown ablation profile {profile!r}; expected one of {PROFILE_ORDER}"
        )

    out = copy.deepcopy(config)
    context = out.setdefault("context", {})
    semantic = context.setdefault("semantic", {})
    crg = context.setdefault("crg", {})

    if name == "adaptive":
        return out

    context["external_retrievers"] = []

    if name == "base_only":
        semantic["mode"] = "off"
        semantic["command"] = ""
        crg["mode"] = "off"
    elif name == "base_semantic":
        crg["mode"] = "off"
    elif name == "base_structural":
        semantic["mode"] = "off"
        semantic["command"] = ""

    return out


def _metric_delta(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    key: str,
) -> float | None:
    left = baseline.get(key)
    right = candidate.get(key)
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        return None
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        return None
    return round(float(right) - float(left), 4)


def _profile_delta(
    adaptive: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    base = adaptive.get("summary") or {}
    current = result.get("summary") or {}
    keys = (
        "mean_file_recall_at_k",
        "mean_file_mrr",
        "mean_file_ndcg_at_k",
        "mean_file_f1",
        "mean_file_yield_per_1k_tokens",
        "selective_control_accuracy",
        "mean_estimated_context_tokens",
        "mean_elapsed_ms",
    )
    return {key: _metric_delta(base, current, key) for key in keys}


def run_ablation_suite(
    root,
    config: dict[str, Any],
    tasks: list[dict[str, Any]],
    profiles: list[str] | tuple[str, ...] | None = None,
    *,
    require_frozen_snapshot: bool = False,
    require_research_protocol: bool = False,
) -> dict[str, Any]:
    requested = list(profiles or PROFILE_ORDER)
    normalized = list(dict.fromkeys(str(profile).strip().lower() for profile in requested))
    if not normalized:
        raise ValueError("at least one ablation profile is required")
    for profile in normalized:
        if profile not in PROFILE_ORDER:
            raise ValueError(
                f"unknown ablation profile {profile!r}; expected one of {PROFILE_ORDER}"
            )

    results: dict[str, dict[str, Any]] = {}
    for profile in normalized:
        results[profile] = run_benchmark(
            root,
            profile_config(config, profile),
            tasks,
            require_frozen_snapshot=require_frozen_snapshot,
            require_research_protocol=require_research_protocol,
        )

    adaptive = results.get("adaptive")
    deltas = (
        {
            profile: _profile_delta(adaptive, result)
            for profile, result in results.items()
            if profile != "adaptive"
        }
        if adaptive is not None
        else {}
    )

    return {
        "scope": "retrieval-ablation-suite",
        "profiles": normalized,
        "results": results,
        "delta_vs_adaptive": deltas,
        "note": (
            "Profiles isolate provider families, not ranking mathematics inside "
            "the native base broker. base_only disables semantic, external, and "
            "CRG providers; base_semantic disables CRG/external; "
            "base_structural disables semantic/external."
        ),
    }
