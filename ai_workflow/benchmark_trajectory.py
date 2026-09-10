from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .benchmark_protocol import normalize_file_path


_ALLOWED_KINDS = frozenset({"seed", "explored", "utilized"})


def _safe_relative_path(value: str) -> str:
    path = Path(str(value).strip())
    if not str(value).strip():
        raise ValueError("trajectory path must not be blank")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("trajectory path must stay inside the benchmark root")
    return path.as_posix()


def _normalize_event(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"trajectory event {index} must be an object")

    kind = str(raw.get("kind", "")).strip().lower()
    if kind not in _ALLOWED_KINDS:
        raise ValueError(
            f"trajectory event {index} kind must be one of {sorted(_ALLOWED_KINDS)}"
        )

    file_value = raw.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        raise ValueError(f"trajectory event {index} must define file")

    raw_step = raw.get("step", index)
    if isinstance(raw_step, bool):
        raise ValueError(f"trajectory event {index} step must be an integer")
    try:
        step = int(raw_step)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"trajectory event {index} step must be an integer"
        ) from exc
    if step < 0:
        raise ValueError(f"trajectory event {index} step must be non-negative")

    return {
        "kind": kind,
        "file": normalize_file_path(file_value),
        "step": step,
    }


def load_trajectory_events(
    benchmark_root: Path,
    case: dict[str, Any],
) -> list[dict[str, Any]]:
    inline = case.get("trajectory_events")
    trajectory_file = case.get("trajectory_file")

    if inline is not None and trajectory_file is not None:
        raise ValueError(
            "benchmark case must define either trajectory_events or trajectory_file, not both"
        )

    if inline is not None:
        if not isinstance(inline, list):
            raise ValueError("trajectory_events must be an array")
        return [_normalize_event(raw, index) for index, raw in enumerate(inline, 1)]

    if trajectory_file is None:
        return []

    relative = _safe_relative_path(str(trajectory_file))
    path = (Path(benchmark_root).resolve() / relative).resolve()
    try:
        path.relative_to(Path(benchmark_root).resolve())
    except ValueError as exc:
        raise ValueError("trajectory_file must stay inside the benchmark root") from exc

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read trajectory_file: {relative}") from exc

    if path.suffix.lower() == ".jsonl":
        rows: list[object] = []
        for line_number, line in enumerate(raw_text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL trajectory at line {line_number}: {relative}"
                ) from exc
    else:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON trajectory: {relative}") from exc
        if not isinstance(parsed, list):
            raise ValueError("trajectory JSON must be an array")
        rows = parsed

    return [_normalize_event(raw, index) for index, raw in enumerate(rows, 1)]


def trajectory_metrics(
    events: list[dict[str, Any]],
    gold_files: list[str],
) -> dict[str, Any] | None:
    if not events:
        return None

    gold = {
        normalize_file_path(path)
        for path in gold_files
        if isinstance(path, str) and path.strip()
    }

    ordered = sorted(events, key=lambda event: (int(event["step"]), event["kind"]))
    by_kind = {
        kind: [event for event in ordered if event["kind"] == kind]
        for kind in _ALLOWED_KINDS
    }

    seed_files = [event["file"] for event in by_kind["seed"]]
    explored_files = [event["file"] for event in by_kind["explored"]]
    utilized_files = [event["file"] for event in by_kind["utilized"]]

    seed_unique = list(dict.fromkeys(seed_files))
    explored_unique = list(dict.fromkeys(explored_files))
    utilized_unique = list(dict.fromkeys(utilized_files))

    explored_set = set(explored_unique)
    utilized_set = set(utilized_unique)
    seed_set = set(seed_unique)

    explored_gold = explored_set & gold
    utilized_gold = utilized_set & gold
    seed_gold = seed_set & gold

    first_gold_exploration_step = next(
        (
            int(event["step"])
            for event in ordered
            if event["kind"] == "explored" and event["file"] in gold
        ),
        None,
    )
    first_gold_utilization_step = next(
        (
            int(event["step"])
            for event in ordered
            if event["kind"] == "utilized" and event["file"] in gold
        ),
        None,
    )

    last_seed_step = max(
        (int(event["step"]) for event in by_kind["seed"]),
        default=None,
    )
    post_seed_explored = {
        event["file"]
        for event in by_kind["explored"]
        if last_seed_step is not None and int(event["step"]) > last_seed_step
    }

    exploration_precision = (
        len(explored_gold) / len(explored_set)
        if explored_set
        else None
    )
    exploration_recall = (
        len(explored_gold) / len(gold)
        if gold
        else None
    )
    utilization_precision = (
        len(utilized_gold) / len(utilized_set)
        if utilized_set
        else None
    )
    utilization_recall = (
        len(utilized_gold) / len(gold)
        if gold
        else None
    )

    return {
        "events": len(ordered),
        "seed_unique_files": seed_unique,
        "explored_unique_files": explored_unique,
        "utilized_unique_files": utilized_unique,
        "seed_gold_recall": len(seed_gold) / len(gold) if gold else None,
        "exploration_precision": exploration_precision,
        "exploration_recall": exploration_recall,
        "utilization_precision": utilization_precision,
        "utilization_recall": utilization_recall,
        "context_utilization_rate": (
            len(utilized_set & explored_set) / len(explored_set)
            if explored_set
            else None
        ),
        "gold_utilization_rate": (
            len(utilized_gold) / len(explored_gold)
            if explored_gold
            else None
        ),
        "duplicate_exploration_rate": (
            1.0 - (len(explored_set) / len(explored_files))
            if explored_files
            else 0.0
        ),
        "first_gold_exploration_step": first_gold_exploration_step,
        "first_gold_utilization_step": first_gold_utilization_step,
        "post_seed_exploration_unique_files": len(post_seed_explored),
    }
