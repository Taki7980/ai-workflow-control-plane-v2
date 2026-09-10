from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from .models import ContextItem


POSITIVE_TASK_TYPES = frozenset(
    {"code2test", "comment2context", "trace2code", "edit2ripple"}
)
CONTROL_TYPES = frozenset({"positive", "natural_no_gold", "wrong_repo"})
_PATH_KEYS = ("file", "path", "relative_path", "file_path")
_REPOSITORY_KEYS = ("repository_id", "remote_identity", "repository", "repo", "repo_id")
_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40,64}$")


def normalize_file_path(value: str) -> str:
    normalized = str(value).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = re.sub(r"/+", "/", normalized)
    return normalized.strip("/")


def _json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def context_item_file(item: ContextItem) -> str | None:
    for container in (item.metadata, item.provenance, _json_object(item.text) or {}):
        for key in _PATH_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_file_path(value)

    match = re.match(r"^(?P<path>.+?):\d+(?::\d+)?:\s", item.text)
    if match:
        return normalize_file_path(match.group("path"))

    match = re.search(r"Detected test file:\s+(.+?)\s+\(for\s+", item.text)
    if match:
        return normalize_file_path(match.group(1))
    return None


def context_item_repository(item: ContextItem) -> str | None:
    for container in (item.metadata, item.provenance, _json_object(item.text) or {}):
        for key in _REPOSITORY_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def file_retrieval_metrics(
    items: list[ContextItem],
    gold_files: list[str],
    k: int = 5,
) -> dict[str, Any] | None:
    gold = list(
        dict.fromkeys(
            normalize_file_path(path) for path in gold_files if str(path).strip()
        )
    )
    if not gold:
        return None

    cutoff = max(1, int(k))
    ranked_files: list[str] = []
    seen: set[str] = set()
    for item in items:
        path = context_item_file(item)
        if not path or path in seen:
            continue
        seen.add(path)
        ranked_files.append(path)
        if len(ranked_files) >= cutoff:
            break

    gold_set = set(gold)
    relevance = [int(path in gold_set) for path in ranked_files]
    matched = [path for path in ranked_files if path in gold_set]
    first_relevant = next(
        (rank for rank, hit in enumerate(relevance, 1) if hit),
        None,
    )

    dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(relevance, 1))
    ideal_hits = min(len(gold), cutoff)
    ideal_dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, ideal_hits + 1)
    )

    precision = len(matched) / cutoff
    recall = len(set(matched)) / len(gold_set)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "k": cutoff,
        "gold_files": gold,
        "retrieved_files": ranked_files,
        "matched_gold_files": list(dict.fromkeys(matched)),
        "precision_at_k": precision,
        "recall_at_k": recall,
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "ndcg_at_k": dcg / ideal_dcg if ideal_dcg else 0.0,
        "file_f1": f1,
    }


def repository_control_metrics(
    items: list[ContextItem],
    forbidden_repositories: list[str],
    k: int = 5,
) -> dict[str, Any] | None:
    forbidden = {
        str(value).strip()
        for value in forbidden_repositories
        if str(value).strip()
    }
    if not forbidden:
        return None

    cutoff = max(1, int(k))
    observed: list[str] = []
    contaminated: list[str] = []
    inspected = 0
    for item in items[:cutoff]:
        inspected += 1
        identity = context_item_repository(item)
        if identity is None:
            continue
        observed.append(identity)
        if identity in forbidden:
            contaminated.append(identity)

    return {
        "k": cutoff,
        "identity_coverage": len(observed) / max(1, inspected),
        "observed_repositories": list(dict.fromkeys(observed)),
        "forbidden_repositories": sorted(forbidden),
        "contamination_count": len(contaminated),
        "contamination_rate": len(contaminated) / cutoff,
    }


def validate_benchmark_cases(
    tasks: list[dict[str, Any]],
    *,
    require_research_protocol: bool = False,
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    for index, case in enumerate(tasks, 1):
        if not isinstance(case, dict):
            raise ValueError(f"benchmark case {index} must be an object")

        task = str(case.get("task", "")).strip()
        if not task:
            raise ValueError(
                f"benchmark case {index} must define a non-empty task"
            )

        try:
            retrieval_k = int(case.get("retrieval_k", 5))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"benchmark case {index} retrieval_k must be an integer"
            ) from exc
        if retrieval_k < 1:
            raise ValueError(
                f"benchmark case {index} retrieval_k must be >= 1"
            )

        task_type = case.get("task_type")
        if task_type is not None:
            task_type = str(task_type).strip()
            allowed = POSITIVE_TASK_TYPES | {"no_gold"}
            if task_type not in allowed:
                raise ValueError(
                    f"benchmark case {index} task_type must be one of "
                    f"{sorted(allowed)}"
                )
        elif require_research_protocol:
            raise ValueError(
                f"benchmark case {index} must define task_type"
            )

        control_type = str(case.get("control_type", "positive")).strip()
        if control_type not in CONTROL_TYPES:
            raise ValueError(
                f"benchmark case {index} control_type must be one of "
                f"{sorted(CONTROL_TYPES)}"
            )

        gold_files = case.get("gold_files") or []
        if not isinstance(gold_files, list) or not all(
            isinstance(path, str) and path.strip() for path in gold_files
        ):
            raise ValueError(
                f"benchmark case {index} gold_files must be a list of paths"
            )

        if task_type in POSITIVE_TASK_TYPES and not gold_files:
            raise ValueError(
                f"benchmark case {index} task_type={task_type} "
                "requires gold_files"
            )
        if control_type != "positive" and gold_files:
            raise ValueError(
                f"benchmark case {index} selective controls must not "
                "define gold_files"
            )

        base_commit = case.get("base_commit")
        if base_commit is not None and not _GIT_SHA.fullmatch(
            str(base_commit).strip()
        ):
            raise ValueError(
                f"benchmark case {index} base_commit must be a full "
                "40-64 digit Git object ID"
            )
        if require_research_protocol and not base_commit:
            raise ValueError(
                f"benchmark case {index} must define base_commit"
            )

        repository_path = str(
            case.get("repository_path", ".")
        ).strip() or "."
        repo_parts = Path(repository_path).parts
        if Path(repository_path).is_absolute() or ".." in repo_parts:
            raise ValueError(
                f"benchmark case {index} repository_path must stay inside "
                "the benchmark root"
            )

        forbidden = case.get("forbidden_repositories") or []
        if not isinstance(forbidden, list) or not all(
            isinstance(value, str) and value.strip()
            for value in forbidden
        ):
            raise ValueError(
                f"benchmark case {index} forbidden_repositories must be "
                "a list of identities"
            )
        if (
            control_type == "wrong_repo"
            and require_research_protocol
            and not forbidden
        ):
            raise ValueError(
                f"benchmark case {index} wrong_repo control requires "
                "forbidden_repositories"
            )

        validated.append(case)
    return validated


def snapshot_status(
    root: Path,
    case: dict[str, Any],
) -> dict[str, Any]:
    expected = str(case.get("base_commit", "")).strip() or None
    repository_path = str(
        case.get("repository_path", ".")
    ).strip() or "."
    if expected is None:
        return {
            "status": "not_declared",
            "repository_path": repository_path,
            "expected_head": None,
            "actual_head": None,
            "match": None,
        }

    workspace_root = Path(root).resolve()
    repository_root = (workspace_root / repository_path).resolve()
    try:
        repository_root.relative_to(workspace_root)
    except ValueError:
        return {
            "status": "invalid_path",
            "repository_path": repository_path,
            "expected_head": expected,
            "actual_head": None,
            "match": False,
        }

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None

    actual = (
        proc.stdout.strip()
        if proc is not None and proc.returncode == 0
        else None
    )
    if actual is None:
        return {
            "status": "unavailable",
            "repository_path": repository_path,
            "expected_head": expected,
            "actual_head": None,
            "match": False,
        }

    match = actual == expected
    return {
        "status": "match" if match else "mismatch",
        "repository_path": repository_path,
        "expected_head": expected,
        "actual_head": actual,
        "match": match,
    }
