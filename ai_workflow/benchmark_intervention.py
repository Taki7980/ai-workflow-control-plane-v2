from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .benchmark import run_benchmark
from .benchmark_protocol import normalize_file_path, resolve_case_root, snapshot_status
from .benchmark_trajectory import load_trajectory_events, trajectory_metrics
from .provider_runner import build_provider_env


SEED_MODES = ("retrieval", "random_non_gold", "oracle_gold")
DEFAULT_RUNNER_OUTPUT_BYTES = 4 * 1024 * 1024


def tracked_files(root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"unable to enumerate tracked files in {root}") from exc
    if proc.returncode != 0:
        raise ValueError(f"unable to enumerate tracked files in {root}")
    return sorted(
        {
            normalize_file_path(raw.decode("utf-8", errors="replace"))
            for raw in proc.stdout.split(b"\0")
            if raw
        }
    )


def deterministic_non_gold_sample(
    files: Iterable[str],
    gold_files: Iterable[str],
    key: str,
    k: int,
) -> list[str]:
    limit = max(1, int(k))
    gold = {
        normalize_file_path(path)
        for path in gold_files
        if str(path).strip()
    }
    candidates = {
        normalize_file_path(path)
        for path in files
        if str(path).strip()
    } - gold

    def rank(path: str) -> bytes:
        payload = f"{key}\0{path}".encode("utf-8")
        return hashlib.sha256(payload).digest()

    return sorted(candidates, key=lambda path: (rank(path), path))[:limit]


def seed_metrics(
    seed_files: Iterable[str],
    gold_files: Iterable[str],
) -> dict[str, Any]:
    seed = list(
        dict.fromkeys(
            normalize_file_path(path)
            for path in seed_files
            if str(path).strip()
        )
    )
    gold = {
        normalize_file_path(path)
        for path in gold_files
        if str(path).strip()
    }
    matched = [path for path in seed if path in gold]
    precision = len(matched) / len(seed) if seed else 0.0
    recall = len(set(matched)) / len(gold) if gold else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if recall is not None and precision + recall
        else 0.0
    )
    return {
        "seed_count": len(seed),
        "matched_gold_files": matched,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _case_key(case: dict[str, Any], index: int) -> str:
    return "|".join(
        (
            str(index),
            str(case.get("repository_path", ".")),
            str(case.get("base_commit", "")),
            str(case.get("task", "")),
        )
    )


def _retrieval_seed_files(row: dict[str, Any], seed_k: int) -> list[str]:
    metrics = row.get("file_retrieval") or {}
    files = metrics.get("retrieved_files") or []
    return [
        normalize_file_path(path)
        for path in files
        if isinstance(path, str) and path.strip()
    ][:seed_k]


def build_seed_intervention_manifest(
    root: Path,
    config: dict[str, Any],
    tasks: list[dict[str, Any]],
    modes: list[str] | tuple[str, ...] | None = None,
    *,
    seed_k: int = 5,
    require_frozen_snapshot: bool = False,
    require_research_protocol: bool = False,
) -> dict[str, Any]:
    limit = max(1, int(seed_k))
    requested = list(modes or SEED_MODES)
    normalized_modes = list(
        dict.fromkeys(str(mode).strip().lower() for mode in requested)
    )
    if not normalized_modes:
        raise ValueError("at least one seed mode is required")
    for mode in normalized_modes:
        if mode not in SEED_MODES:
            raise ValueError(
                f"unknown seed mode {mode!r}; expected one of {SEED_MODES}"
            )

    benchmark_tasks: list[dict[str, Any]] = []
    for case in tasks:
        copied = dict(case)
        copied["retrieval_k"] = max(
            limit,
            int(copied.get("retrieval_k", limit)),
        )
        benchmark_tasks.append(copied)

    benchmark = run_benchmark(
        root,
        config,
        benchmark_tasks,
        require_frozen_snapshot=require_frozen_snapshot,
        require_research_protocol=require_research_protocol,
    )

    interventions: list[dict[str, Any]] = []
    for index, (case, row) in enumerate(
        zip(benchmark_tasks, benchmark["cases"]),
        1,
    ):
        gold_files = [
            normalize_file_path(path)
            for path in case.get("gold_files") or []
            if isinstance(path, str) and path.strip()
        ]
        if not gold_files:
            continue

        case_root = resolve_case_root(root, case)
        snapshot = snapshot_status(root, case)
        tracked = tracked_files(case_root)
        retrieval_seed = _retrieval_seed_files(row, limit)
        oracle_seed = list(dict.fromkeys(gold_files))[:limit]
        random_seed = deterministic_non_gold_sample(
            tracked,
            gold_files,
            _case_key(case, index),
            limit,
        )
        seeds = {
            "retrieval": retrieval_seed,
            "random_non_gold": random_seed,
            "oracle_gold": oracle_seed,
        }

        for mode in normalized_modes:
            seed_files = seeds[mode]
            interventions.append(
                {
                    "case_index": index,
                    "task": case["task"],
                    "task_type": case.get("task_type"),
                    "repository_path": case.get("repository_path", "."),
                    "base_commit": case.get("base_commit"),
                    "snapshot": snapshot,
                    "seed_mode": mode,
                    "seed_files": seed_files,
                    "gold_files": gold_files,
                    "seed_metrics": seed_metrics(seed_files, gold_files),
                }
            )

    return {
        "scope": "seed-intervention-manifest",
        "seed_k": limit,
        "modes": normalized_modes,
        "interventions": interventions,
        "benchmark_summary": benchmark.get("summary") or {},
        "note": (
            "random_non_gold is deterministic, excludes exact gold files, "
            "and is keyed by case identity so repeated runs are reproducible."
        ),
    }


def _runner_payload(
    root: Path,
    intervention: dict[str, Any],
) -> dict[str, Any]:
    case = {
        "repository_path": intervention.get("repository_path", "."),
    }
    case_root = resolve_case_root(root, case)
    return {
        "task": intervention["task"],
        "task_type": intervention.get("task_type"),
        "repository_root": str(case_root),
        "repository_path": intervention.get("repository_path", "."),
        "base_commit": intervention.get("base_commit"),
        "seed_mode": intervention["seed_mode"],
        "seed_files": intervention["seed_files"],
        "gold_files": intervention["gold_files"],
    }


def run_intervention_runner(
    root: Path,
    intervention: dict[str, Any],
    command: list[str] | tuple[str, ...],
    *,
    timeout_seconds: float = 120.0,
    max_output_bytes: int = DEFAULT_RUNNER_OUTPUT_BYTES,
    env_allowlist: Iterable[str] = (),
) -> dict[str, Any]:
    argv = [str(part) for part in command if str(part)]
    if not argv:
        raise ValueError("runner command must not be empty")
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise ValueError("runner timeout must be positive")
    output_limit = int(max_output_bytes)
    if output_limit <= 0:
        raise ValueError("runner max output bytes must be positive")

    payload = _runner_payload(root, intervention)
    case_root = Path(payload["repository_root"])
    raw_input = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        with tempfile.TemporaryFile() as stdout_file:
            proc = subprocess.run(
                argv,
                cwd=case_root,
                input=raw_input,
                stdout=stdout_file,
                stderr=subprocess.DEVNULL,
                env=build_provider_env(env_allowlist),
                timeout=timeout,
                check=False,
            )
            output_size = stdout_file.tell()
            if output_size > output_limit:
                return {
                    "status": "output_limit",
                    "success": None,
                    "trajectory": None,
                    "error": f"runner output exceeded {output_limit} bytes",
                }
            stdout_file.seek(0)
            raw_output = stdout_file.read(output_limit + 1)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "success": None,
            "trajectory": None,
            "error": f"runner timed out after {timeout:g} seconds",
        }
    except (OSError, ValueError) as exc:
        return {
            "status": "launch_error",
            "success": None,
            "trajectory": None,
            "error": f"runner could not start: {type(exc).__name__}",
        }

    if proc.returncode != 0:
        return {
            "status": "exit_error",
            "success": None,
            "trajectory": None,
            "error": f"runner exited with status {proc.returncode}",
        }

    try:
        decoded = json.loads(raw_output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_output",
            "success": None,
            "trajectory": None,
            "error": "runner must return one JSON object",
        }
    if not isinstance(decoded, dict):
        return {
            "status": "invalid_output",
            "success": None,
            "trajectory": None,
            "error": "runner must return one JSON object",
        }

    raw_events = decoded.get("trajectory_events") or []
    if not isinstance(raw_events, list):
        return {
            "status": "invalid_output",
            "success": None,
            "trajectory": None,
            "error": "runner trajectory_events must be an array",
        }

    seed_events = [
        {"kind": "seed", "file": path, "step": 0}
        for path in intervention["seed_files"]
    ]
    try:
        events = load_trajectory_events(
            root,
            {"trajectory_events": [*seed_events, *raw_events]},
        )
    except ValueError as exc:
        return {
            "status": "invalid_output",
            "success": None,
            "trajectory": None,
            "error": str(exc),
        }

    success = decoded.get("success")
    if success is not None and not isinstance(success, bool):
        success = None

    return {
        "status": "ok",
        "success": success,
        "trajectory": trajectory_metrics(
            events,
            intervention["gold_files"],
        ),
        "metadata": (
            dict(decoded.get("metadata") or {})
            if isinstance(decoded.get("metadata"), dict)
            else {}
        ),
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(row[key])
        for row in rows
        if isinstance(row.get(key), (int, float))
        and not isinstance(row.get(key), bool)
    ]
    return round(statistics.mean(values), 4) if values else None


def _seed_mode_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("runner", {}).get("status") == "ok"]
    trajectories = [
        row["runner"]["trajectory"]
        for row in ok
        if isinstance(row["runner"].get("trajectory"), dict)
    ]
    seed_rows = [
        row["seed_metrics"]
        for row in rows
        if isinstance(row.get("seed_metrics"), dict)
    ]
    successes = [
        bool(row["runner"]["success"])
        for row in ok
        if isinstance(row["runner"].get("success"), bool)
    ]
    return {
        "runs": len(rows),
        "completed_runs": len(ok),
        "success_rate": (
            round(sum(successes) / len(successes), 4)
            if successes
            else None
        ),
        "mean_seed_precision": _mean(seed_rows, "precision"),
        "mean_seed_recall": _mean(seed_rows, "recall"),
        "mean_seed_f1": _mean(seed_rows, "f1"),
        "mean_seed_gold_recall": _mean(trajectories, "seed_gold_recall"),
        "mean_exploration_recall": _mean(trajectories, "exploration_recall"),
        "mean_utilization_recall": _mean(trajectories, "utilization_recall"),
        "mean_context_utilization_rate": _mean(
            trajectories,
            "context_utilization_rate",
        ),
        "mean_duplicate_exploration_rate": _mean(
            trajectories,
            "duplicate_exploration_rate",
        ),
        "mean_post_seed_exploration_unique_files": _mean(
            trajectories,
            "post_seed_exploration_unique_files",
        ),
    }


def _paired_delta_vs_random(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_case: dict[int, dict[str, dict[str, Any]]] = {}
    for row in rows:
        case_index = int(row["case_index"])
        by_case.setdefault(case_index, {})[str(row["seed_mode"])] = row

    metric_keys = (
        "exploration_recall",
        "utilization_recall",
        "context_utilization_rate",
        "duplicate_exploration_rate",
        "post_seed_exploration_unique_files",
    )
    paired: dict[str, list[dict[str, float]]] = {}
    for modes in by_case.values():
        baseline = modes.get("random_non_gold")
        if baseline is None:
            continue
        baseline_runner = baseline.get("runner") or {}
        baseline_traj = baseline_runner.get("trajectory")
        if not isinstance(baseline_traj, dict):
            continue
        for mode, row in modes.items():
            if mode == "random_non_gold":
                continue
            current_traj = (row.get("runner") or {}).get("trajectory")
            if not isinstance(current_traj, dict):
                continue
            deltas: dict[str, float] = {}
            for key in metric_keys:
                left = baseline_traj.get(key)
                right = current_traj.get(key)
                if (
                    isinstance(left, (int, float))
                    and not isinstance(left, bool)
                    and isinstance(right, (int, float))
                    and not isinstance(right, bool)
                ):
                    deltas[key] = float(right) - float(left)
            paired.setdefault(mode, []).append(deltas)

    return {
        mode: {
            "paired_cases": len(values),
            **{
                f"mean_delta_{key}": _mean(values, key)
                for key in metric_keys
            },
        }
        for mode, values in sorted(paired.items())
    }


def run_seed_interventions(
    root: Path,
    manifest: dict[str, Any],
    command: list[str] | tuple[str, ...],
    *,
    timeout_seconds: float = 120.0,
    max_output_bytes: int = DEFAULT_RUNNER_OUTPUT_BYTES,
    env_allowlist: Iterable[str] = (),
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for intervention in manifest.get("interventions") or []:
        row = dict(intervention)
        row["runner"] = run_intervention_runner(
            root,
            intervention,
            command,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            env_allowlist=env_allowlist,
        )
        rows.append(row)

    by_mode: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_mode.setdefault(str(row["seed_mode"]), []).append(row)

    return {
        "scope": "seed-intervention-run",
        "seed_k": manifest.get("seed_k"),
        "results": rows,
        "by_seed_mode": {
            mode: _seed_mode_summary(group)
            for mode, group in sorted(by_mode.items())
        },
        "paired_delta_vs_random_non_gold": _paired_delta_vs_random(rows),
        "note": (
            "Runner commands execute only when explicitly supplied to the "
            "benchmark-intervene CLI and receive a restricted environment."
        ),
    }
