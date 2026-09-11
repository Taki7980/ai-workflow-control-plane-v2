from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .benchmark_protocol import validate_benchmark_cases


CORPUS_SCHEMA_VERSION = 2
_REQUIRED_SOURCE_FIELDS = ("name", "url", "license")


def load_corpus_document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("benchmark corpus v2 must be a JSON object")
    return value


def validate_corpus_document(
    document: dict[str, Any],
) -> dict[str, Any]:
    if document.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise ValueError("benchmark corpus schema_version must be 2")
    corpus_id = str(document.get("corpus_id", "")).strip()
    if not corpus_id:
        raise ValueError("benchmark corpus must define corpus_id")
    source = document.get("source")
    if not isinstance(source, dict):
        raise ValueError("benchmark corpus must define source metadata")
    for field in _REQUIRED_SOURCE_FIELDS:
        if not str(source.get(field, "")).strip():
            raise ValueError(
                f"benchmark corpus source must define {field}"
            )
    split = str(document.get("split", "")).strip()
    if not split:
        raise ValueError("benchmark corpus must define split")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise ValueError("benchmark corpus cases must be a list")
    validate_benchmark_cases(
        cases,
        require_research_protocol=True,
    )
    return document


def corpus_summary(document: dict[str, Any]) -> dict[str, Any]:
    validate_corpus_document(document)
    task_types: dict[str, int] = {}
    controls: dict[str, int] = {}
    languages: dict[str, int] = {}
    repositories: set[str] = set()
    span_cases = 0
    for case in document["cases"]:
        task_type = str(case.get("task_type", "unknown"))
        task_types[task_type] = task_types.get(task_type, 0) + 1
        control = str(case.get("control_type", "positive"))
        controls[control] = controls.get(control, 0) + 1
        language = str(case.get("language", "unknown"))
        languages[language] = languages.get(language, 0) + 1
        if case.get("gold_spans"):
            span_cases += 1
        repository_id = str(case.get("repository_id", "")).strip()
        if repository_id:
            repositories.add(repository_id)
    summary = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "corpus_id": document["corpus_id"],
        "split": document["split"],
        "source": document["source"],
        "cases": len(document["cases"]),
        "span_labeled_cases": span_cases,
        "task_types": dict(sorted(task_types.items())),
        "control_types": dict(sorted(controls.items())),
        "languages": dict(sorted(languages.items())),
        "repositories": len(repositories),
    }
    summary["publication_readiness"] = publication_readiness(summary)
    return summary


def publication_readiness(
    summary: dict[str, Any],
    *,
    minimum_cases: int = 427,
    minimum_repositories: int = 25,
    minimum_languages: int = 4,
) -> dict[str, Any]:
    cases = int(summary.get("cases", 0))
    repositories = int(summary.get("repositories", 0))
    languages = summary.get("languages")
    language_count = len(languages) if isinstance(languages, dict) else 0
    control_types = summary.get("control_types")
    controls = control_types if isinstance(control_types, dict) else {}
    span_cases = int(summary.get("span_labeled_cases", 0))
    blockers: list[str] = []
    if cases < minimum_cases:
        blockers.append("insufficient_cases")
    if repositories < minimum_repositories:
        blockers.append("insufficient_repositories")
    if language_count < minimum_languages:
        blockers.append("insufficient_language_diversity")
    if int(controls.get("natural_no_gold", 0)) < 1:
        blockers.append("missing_natural_no_gold_controls")
    if int(controls.get("wrong_repo", 0)) < 1:
        blockers.append("missing_wrong_repo_controls")
    if span_cases < 1:
        blockers.append("missing_span_labels")
    return {
        "ready": not blockers,
        "reference_floor": "Agent Retrieval Bench scale floor",
        "minimum_cases": minimum_cases,
        "minimum_repositories": minimum_repositories,
        "minimum_languages": minimum_languages,
        "blockers": blockers,
    }


def canonical_cases(document: dict[str, Any]) -> list[dict[str, Any]]:
    validate_corpus_document(document)
    return [dict(case) for case in document["cases"]]
