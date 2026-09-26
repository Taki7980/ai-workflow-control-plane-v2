from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .benchmark_corpus import validate_corpus_document
from .benchmark_protocol import normalize_file_path


INTEGRITY_SCHEMA_VERSION = 1
_SPLIT_ALIASES = {
    "development": "development",
    "dev": "development",
    "train": "development",
    "calibration": "calibration",
    "calibrate": "calibration",
    "validation": "calibration",
    "val": "calibration",
    "holdout": "holdout",
    "test": "holdout",
    "evaluation": "holdout",
    "eval": "holdout",
    "ci": "ci",
    "smoke": "ci",
}
_PROTECTED_SPLITS = ("development", "calibration", "holdout")
_TEMPORAL_FIELDS = (
    "source_event_time",
    "issue_created_at",
    "created_at",
    "observed_at",
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")
_HISTORY_ISOLATION_VALUES = {
    "git_metadata_removed",
    "exported_tree",
    "sandboxed_no_history",
}


def canonical_document_sha256(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def split_role(document: dict[str, Any]) -> str | None:
    explicit = str(document.get("split_role", "")).strip().lower()
    if explicit:
        if explicit not in {*_PROTECTED_SPLITS, "ci", "other"}:
            raise ValueError(
                "benchmark corpus split_role must be development, "
                "calibration, holdout, ci, or other"
            )
        return explicit
    raw = str(document.get("split", "")).strip().lower()
    return _SPLIT_ALIASES.get(raw)


def _normalized_task(value: str) -> str:
    tokens = _TOKEN_RE.findall(value.casefold())
    return " ".join(tokens)


def _task_shingles(value: str, width: int = 3) -> set[tuple[str, ...]]:
    tokens = _normalized_task(value).split()
    if len(tokens) < max(width, 6):
        return set()
    return {
        tuple(tokens[index : index + width])
        for index in range(len(tokens) - width + 1)
    }


def _jaccard(
    left: set[tuple[str, ...]],
    right: set[tuple[str, ...]],
) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def task_fingerprint(case: dict[str, Any]) -> str:
    payload = {
        "task": _normalized_task(str(case.get("task", ""))),
        "task_type": str(case.get("task_type", "")).strip().lower(),
        "control_type": str(case.get("control_type", "positive"))
        .strip()
        .lower(),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_instance_fingerprint(case: dict[str, Any]) -> str:
    spans = []
    for raw in case.get("gold_spans") or []:
        if not isinstance(raw, dict):
            continue
        spans.append(
            {
                "path": normalize_file_path(str(raw.get("path", ""))),
                "start_line": int(raw.get("start_line", 0)),
                "end_line": int(raw.get("end_line", 0)),
            }
        )
    payload = {
        "repository_id": str(case.get("repository_id", "")).strip(),
        "base_commit": str(case.get("base_commit", "")).strip().lower(),
        "gold_files": sorted(
            normalize_file_path(str(path))
            for path in (case.get("gold_files") or [])
        ),
        "gold_spans": sorted(
            spans,
            key=lambda row: (
                row["path"],
                row["start_line"],
                row["end_line"],
            ),
        ),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_temporal_value(case: dict[str, Any]) -> tuple[str | None, bool]:
    for field in _TEMPORAL_FIELDS:
        raw = case.get(field)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value:
            continue
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            return field, False
        return field, True
    return None, False


def _contains_hint(task: str, hint: str) -> bool:
    normalized_hint = hint.strip().casefold()
    if not normalized_hint:
        return False
    return normalized_hint in task.casefold()


def _gold_path_hints(case: dict[str, Any]) -> list[str]:
    task = str(case.get("task", ""))
    exposed: list[str] = []
    for raw_path in case.get("gold_files") or []:
        path = normalize_file_path(str(raw_path))
        if not path:
            continue
        basename = Path(path).name
        if _contains_hint(task, path):
            exposed.append(path)
        elif len(basename) >= 6 and _contains_hint(task, basename):
            exposed.append(basename)
    return sorted(set(exposed))


def _repository_hints(case: dict[str, Any]) -> list[str]:
    task = str(case.get("task", ""))
    repository_id = str(case.get("repository_id", "")).strip()
    if not repository_id:
        return []
    candidates = {repository_id}
    if "/" in repository_id:
        candidates.add(repository_id.rsplit("/", 1)[-1])
    return sorted(
        hint
        for hint in candidates
        if len(hint) >= 5 and _contains_hint(task, hint)
    )


def _issue(
    code: str,
    message: str,
    *,
    corpora: Iterable[str] = (),
    splits: Iterable[str] = (),
    case_ids: Iterable[str] = (),
    repositories: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "corpora": sorted(set(corpora)),
        "splits": sorted(set(splits)),
        "case_ids": sorted(set(case_ids)),
        "repositories": sorted(set(repositories)),
    }


def analyze_partition_integrity(
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    if not documents:
        raise ValueError("benchmark integrity requires at least one corpus")

    blockers: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    corpus_rows: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    case_ids: dict[str, list[dict[str, Any]]] = defaultdict(list)
    task_fingerprints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_fingerprints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repositories_by_split: dict[str, set[str]] = defaultdict(set)

    for document in documents:
        validate_corpus_document(document)
        corpus_id = str(document["corpus_id"]).strip()
        role = split_role(document)
        if role is None:
            signals.append(
                _issue(
                    "unclassified_split",
                    "Corpus split is not mapped to a protected split role.",
                    corpora=[corpus_id],
                    splits=[str(document.get("split", ""))],
                )
            )

        corpus_rows.append(
            {
                "corpus_id": corpus_id,
                "split": str(document["split"]),
                "split_role": role or "unclassified",
                "document_sha256": canonical_document_sha256(document),
                "cases": len(document["cases"]),
                "history_isolation": str(
                    document.get("history_isolation", "")
                ).strip()
                or None,
            }
        )

        if role == "holdout":
            history_isolation = str(
                document.get("history_isolation", "")
            ).strip()
            if history_isolation not in _HISTORY_ISOLATION_VALUES:
                signals.append(
                    _issue(
                        "holdout_history_isolation_unverified",
                        (
                            "Holdout corpus does not attest that future Git "
                            "history is unavailable to evaluated agents."
                        ),
                        corpora=[corpus_id],
                        splits=[role],
                    )
                )

        for case in document["cases"]:
            case_id = str(case.get("case_id", "")).strip()
            repository_id = str(case.get("repository_id", "")).strip()
            record = {
                "corpus_id": corpus_id,
                "split": role or "unclassified",
                "case_id": case_id,
                "repository_id": repository_id,
                "task": str(case.get("task", "")),
                "task_fingerprint": task_fingerprint(case),
            }
            case_records.append(record)
            if role in _PROTECTED_SPLITS and not case_id:
                blockers.append(
                    _issue(
                        "missing_stable_case_id",
                        "Protected benchmark case requires a stable case_id.",
                        corpora=[corpus_id],
                        splits=[role],
                        repositories=[repository_id],
                    )
                )
            case_ids[case_id].append(record)
            task_fingerprints[task_fingerprint(case)].append(record)
            source_fingerprints[source_instance_fingerprint(case)].append(record)

            if role in _PROTECTED_SPLITS and repository_id:
                repositories_by_split[role].add(repository_id)

            temporal_field, temporal_valid = _parse_temporal_value(case)
            if role in _PROTECTED_SPLITS:
                if temporal_field is None:
                    signals.append(
                        _issue(
                            "missing_temporal_provenance",
                            "Protected benchmark case lacks source-event time metadata.",
                            corpora=[corpus_id],
                            splits=[role],
                            case_ids=[case_id],
                            repositories=[repository_id],
                        )
                    )
                elif not temporal_valid:
                    blockers.append(
                        _issue(
                            "invalid_temporal_provenance",
                            "Benchmark case has malformed source-event time metadata.",
                            corpora=[corpus_id],
                            splits=[role],
                            case_ids=[case_id],
                            repositories=[repository_id],
                        )
                    )

            gold_hints = _gold_path_hints(case)
            if gold_hints:
                signals.append(
                    _issue(
                        "gold_path_exposed_in_task",
                        "Task text exposes one or more gold file hints.",
                        corpora=[corpus_id],
                        splits=[role or "unclassified"],
                        case_ids=[case_id],
                        repositories=[repository_id],
                    )
                    | {"hints": gold_hints}
                )

            repo_hints = _repository_hints(case)
            if repo_hints:
                signals.append(
                    _issue(
                        "repository_identity_exposed_in_task",
                        "Task text exposes repository identity hints.",
                        corpora=[corpus_id],
                        splits=[role or "unclassified"],
                        case_ids=[case_id],
                        repositories=[repository_id],
                    )
                    | {"hints": repo_hints}
                )

            if role == "holdout":
                if not str(case.get("base_commit", "")).strip():
                    blockers.append(
                        _issue(
                            "holdout_missing_base_commit",
                            "Holdout case must pin a full base commit.",
                            corpora=[corpus_id],
                            splits=[role],
                            case_ids=[case_id],
                            repositories=[repository_id],
                        )
                    )
                if not str(case.get("content_manifest_sha256", "")).strip():
                    blockers.append(
                        _issue(
                            "holdout_missing_content_manifest",
                            "Holdout case must pin tracked-content identity.",
                            corpora=[corpus_id],
                            splits=[role],
                            case_ids=[case_id],
                            repositories=[repository_id],
                        )
                    )

    for case_id, records in case_ids.items():
        if case_id and len(records) > 1:
            blockers.append(
                _issue(
                    "duplicate_case_id",
                    f"case_id appears in {len(records)} corpus entries.",
                    corpora=[row["corpus_id"] for row in records],
                    splits=[row["split"] for row in records],
                    case_ids=[case_id],
                    repositories=[row["repository_id"] for row in records],
                )
            )

    for records in task_fingerprints.values():
        splits = {row["split"] for row in records}
        protected = splits.intersection(_PROTECTED_SPLITS)
        if len(records) > 1 and len(protected) > 1:
            blockers.append(
                _issue(
                    "cross_split_task_duplicate",
                    "Normalized task fingerprint appears across protected splits.",
                    corpora=[row["corpus_id"] for row in records],
                    splits=protected,
                    case_ids=[row["case_id"] for row in records],
                    repositories=[row["repository_id"] for row in records],
                )
            )

    for left_index, left in enumerate(case_records):
        if left["split"] not in _PROTECTED_SPLITS:
            continue
        for right in case_records[left_index + 1 :]:
            if right["split"] not in _PROTECTED_SPLITS:
                continue
            if left["split"] == right["split"]:
                continue
            if left["task_fingerprint"] == right["task_fingerprint"]:
                continue
            similarity = _jaccard(
                _task_shingles(left["task"]),
                _task_shingles(right["task"]),
            )
            if similarity >= 0.90:
                signals.append(
                    _issue(
                        "cross_split_near_duplicate_task",
                        (
                            "Task wording is highly similar across protected "
                            "splits."
                        ),
                        corpora=[
                            left["corpus_id"],
                            right["corpus_id"],
                        ],
                        splits=[left["split"], right["split"]],
                        case_ids=[
                            left["case_id"],
                            right["case_id"],
                        ],
                        repositories=[
                            left["repository_id"],
                            right["repository_id"],
                        ],
                    )
                    | {"similarity": round(similarity, 4)}
                )

    for records in source_fingerprints.values():
        splits = {row["split"] for row in records}
        protected = splits.intersection(_PROTECTED_SPLITS)
        if len(records) > 1 and len(protected) > 1:
            blockers.append(
                _issue(
                    "cross_split_source_instance_duplicate",
                    "Same repository/base/gold source instance appears across protected splits.",
                    corpora=[row["corpus_id"] for row in records],
                    splits=protected,
                    case_ids=[row["case_id"] for row in records],
                    repositories=[row["repository_id"] for row in records],
                )
            )

    for left_index, left in enumerate(_PROTECTED_SPLITS):
        for right in _PROTECTED_SPLITS[left_index + 1 :]:
            overlap = repositories_by_split[left].intersection(
                repositories_by_split[right]
            )
            if overlap:
                blockers.append(
                    _issue(
                        "cross_split_repository_overlap",
                        "Protected splits must be repository-disjoint.",
                        splits=[left, right],
                        repositories=overlap,
                    )
                )

    present_roles = {
        row["split_role"]
        for row in corpus_rows
        if row["split_role"] in _PROTECTED_SPLITS
    }
    missing_roles = sorted(set(_PROTECTED_SPLITS) - present_roles)
    if missing_roles:
        signals.append(
            _issue(
                "incomplete_partition_set",
                "Integrity report does not include every protected split role.",
                splits=missing_roles,
            )
        )

    return {
        "schema_version": INTEGRITY_SCHEMA_VERSION,
        "ready": not blockers,
        "corpora": sorted(corpus_rows, key=lambda row: row["corpus_id"]),
        "protected_splits": list(_PROTECTED_SPLITS),
        "cases": len(case_records),
        "repositories_by_split": {
            split: sorted(repositories_by_split.get(split, set()))
            for split in _PROTECTED_SPLITS
        },
        "blockers": blockers,
        "leakage_signals": signals,
        "limitations": [
            (
                "This gate detects repository/corpus metadata leakage; it cannot "
                "prove whether a model saw benchmark data during pretraining."
            ),
            (
                "Gold/repository hints are reported as signals because real issue "
                "descriptions may legitimately mention files or repository names."
            ),
            (
                "Temporal provenance coverage supports contamination analysis but "
                "does not establish a proprietary model's training cutoff."
            ),
            (
                "History-isolation is an attestation in corpus metadata; execution "
                "environments must still enforce that Git history is inaccessible."
            ),
        ],
    }
