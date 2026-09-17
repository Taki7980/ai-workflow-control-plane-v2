from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .benchmark_corpus import corpus_summary, validate_corpus_document


_REQUIRED_EXTERNAL_SOURCES = ("agent-retrieval-bench", "core-bench")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSONL at {path}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(value, dict):
            raise ValueError(
                f"JSONL row at {path}:{line_number} must be an object"
            )
        rows.append(value)
    return rows


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"external benchmark record requires {field}")
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip().replace("\\", "/")
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _arb_task(query: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for field in ("pr_title", "pr_body"):
        value = str(query.get(field) or "").strip()
        if value and value not in parts:
            parts.append(value)
    changed_file = str(query.get("changed_file") or "").strip()
    if changed_file:
        parts.append(f"Changed file: {changed_file}")
    if not parts:
        for key in sorted(query):
            value = query[key]
            if isinstance(value, (str, int, float, bool)):
                text = str(value).strip()
                if text:
                    parts.append(f"{key}: {text}")
    if not parts:
        raise ValueError("Agent Retrieval Bench query is empty")
    return "\n".join(parts)


def _arb_gold_files(task_type: str, gold: Mapping[str, Any]) -> list[str]:
    if task_type == "code2test":
        fields = ("related_tests",)
    elif task_type == "comment2context":
        fields = ("supporting_files", "root_cause_files")
    elif task_type == "trace2code":
        fields = ("root_cause_files", "supporting_files")
    elif task_type == "edit2ripple":
        fields = ("root_cause_files", "supporting_files", "related_tests")
    else:
        raise ValueError(f"unsupported Agent Retrieval Bench task_type: {task_type}")

    result: list[str] = []
    seen: set[str] = set()
    for field in fields:
        for path in _string_list(gold.get(field)):
            if path not in seen:
                seen.add(path)
                result.append(path)
    if not result:
        raise ValueError(
            f"Agent Retrieval Bench {task_type} case has no file-level gold"
        )
    return result


def adapt_agent_retrieval_bench(
    records: Sequence[Mapping[str, Any]],
    *,
    corpus_id: str,
    source_url: str,
    license_statement: str,
    split: str,
    repository_paths: Mapping[str, str] | None = None,
    languages: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository_paths = repository_paths or {}
    languages = languages or {}
    cases: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"Agent Retrieval Bench record {index} must be an object")
        case_id = _text(record.get("id"), "id")
        repository_id = _text(record.get("repo"), "repo")
        base_commit = _text(record.get("base_commit"), "base_commit")
        task_type = _text(record.get("task_type"), "task_type")
        query = record.get("query")
        gold = record.get("gold")
        if not isinstance(query, Mapping):
            raise ValueError(f"Agent Retrieval Bench case {case_id} requires query")
        if not isinstance(gold, Mapping):
            raise ValueError(f"Agent Retrieval Bench case {case_id} requires gold")

        metadata = record.get("metadata")
        evidence_source: str | None = None
        if isinstance(metadata, Mapping):
            evidence = metadata.get("evidence")
            if isinstance(evidence, Mapping):
                candidate = str(evidence.get("source") or "").strip()
                evidence_source = candidate or None

        cases.append(
            {
                "schema_version": 1,
                "case_id": case_id,
                "task": _arb_task(query),
                "task_type": task_type,
                "control_type": "positive",
                "repository_id": repository_id,
                "repository_path": repository_paths.get(repository_id, repository_id),
                "base_commit": base_commit,
                "language": languages.get(repository_id, "unknown"),
                "gold_files": _arb_gold_files(task_type, gold),
                "label_source": evidence_source or "agent-retrieval-bench",
                "external_provenance": {
                    "source_id": "agent-retrieval-bench",
                    "upstream_case_id": case_id,
                    "upstream_version": record.get("version"),
                },
            }
        )

    document: dict[str, Any] = {
        "schema_version": 2,
        "corpus_id": _text(corpus_id, "corpus_id"),
        "source": {
            "id": "agent-retrieval-bench",
            "name": "Agent Retrieval Bench",
            "url": _text(source_url, "source_url"),
            "license": _text(license_statement, "license_statement"),
        },
        "split": _text(split, "split"),
        "cases": cases,
    }
    validate_corpus_document(document)
    return document


def _first(record: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    for key in aliases:
        if key in record:
            return record[key]
    return None


def _identifier(record: Mapping[str, Any], kind: str) -> str:
    value = _first(record, ("_id", "id", f"{kind}_id", f"{kind}-id"))
    return _text(value, f"{kind} id")


def _query_text(record: Mapping[str, Any]) -> str:
    return _text(
        _first(record, ("text", "query", "content", "title")),
        "query text",
    )


def _qrel_score(record: Mapping[str, Any]) -> float:
    value = _first(record, ("score", "relevance", "label"))
    if value is None:
        return 1.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"qrel score is not numeric: {value!r}") from exc


def _corpus_file(record: Mapping[str, Any]) -> str | None:
    for container in (record, record.get("metadata")):
        if not isinstance(container, Mapping):
            continue
        value = _first(
            container,
            ("file", "path", "file_path", "relative_path", "source_file"),
        )
        text = str(value or "").strip().replace("\\", "/")
        if text:
            return text
    return None


def adapt_core_bench(
    queries: Sequence[Mapping[str, Any]],
    qrels: Sequence[Mapping[str, Any]],
    corpus: Sequence[Mapping[str, Any]],
    *,
    repository_id: str,
    base_commit: str,
    corpus_id: str,
    source_url: str,
    license_statement: str,
    split: str,
    repository_path: str = ".",
    language: str = "unknown",
    task_type: str = "edit2ripple",
) -> dict[str, Any]:
    corpus_by_id: dict[str, Mapping[str, Any]] = {}
    for record in corpus:
        if not isinstance(record, Mapping):
            raise ValueError("CORE-Bench corpus rows must be objects")
        corpus_by_id[_identifier(record, "corpus")] = record

    qrels_by_query: dict[str, list[Mapping[str, Any]]] = {}
    for qrel in qrels:
        if not isinstance(qrel, Mapping):
            raise ValueError("CORE-Bench qrel rows must be objects")
        query_id = _text(
            _first(qrel, ("query-id", "query_id", "query", "qid")),
            "qrel query id",
        )
        qrels_by_query.setdefault(query_id, []).append(qrel)

    cases: list[dict[str, Any]] = []
    for query in queries:
        if not isinstance(query, Mapping):
            raise ValueError("CORE-Bench query rows must be objects")
        query_id = _identifier(query, "query")
        relevant = [
            qrel
            for qrel in qrels_by_query.get(query_id, [])
            if _qrel_score(qrel) > 0
        ]
        if not relevant:
            raise ValueError(f"CORE-Bench query {query_id} has no positive qrels")

        gold_files: list[str] = []
        seen: set[str] = set()
        for qrel in relevant:
            corpus_id_value = _text(
                _first(
                    qrel,
                    ("corpus-id", "corpus_id", "corpus", "doc_id", "doc-id"),
                ),
                "qrel corpus id",
            )
            record = corpus_by_id.get(corpus_id_value)
            if record is None:
                raise ValueError(
                    f"qrel {query_id}/{corpus_id_value} references missing corpus row"
                )
            path = _corpus_file(record)
            if not path:
                raise ValueError(
                    f"qrel {query_id}/{corpus_id_value} corpus row has no file path"
                )
            if path not in seen:
                seen.add(path)
                gold_files.append(path)

        cases.append(
            {
                "schema_version": 1,
                "case_id": query_id,
                "task": _query_text(query),
                "task_type": task_type,
                "control_type": "positive",
                "repository_id": _text(repository_id, "repository_id"),
                "repository_path": _text(repository_path, "repository_path"),
                "base_commit": _text(base_commit, "base_commit"),
                "language": str(language or "unknown").strip() or "unknown",
                "gold_files": gold_files,
                "label_source": "core-bench-qrels",
                "external_provenance": {
                    "source_id": "core-bench",
                    "upstream_query_id": query_id,
                    "positive_qrels": len(relevant),
                },
            }
        )

    document: dict[str, Any] = {
        "schema_version": 2,
        "corpus_id": _text(corpus_id, "corpus_id"),
        "source": {
            "id": "core-bench",
            "name": "CORE-Bench",
            "url": _text(source_url, "source_url"),
            "license": _text(license_statement, "license_statement"),
        },
        "split": _text(split, "split"),
        "cases": cases,
    }
    validate_corpus_document(document)
    return document


def external_validation_report(
    documents: Sequence[Mapping[str, Any]],
    *,
    required_sources: Sequence[str] = _REQUIRED_EXTERNAL_SOURCES,
    minimum_languages: int = 4,
) -> dict[str, Any]:
    if minimum_languages < 1:
        raise ValueError("minimum_languages must be >= 1")

    seen_corpus_ids: set[str] = set()
    sources: set[str] = set()
    repositories: set[str] = set()
    languages: dict[str, int] = {}
    total_cases = 0
    corpus_reports: list[dict[str, Any]] = []

    for document in documents:
        summary = corpus_summary(dict(document))
        corpus_id = _text(document.get("corpus_id"), "corpus_id")
        if corpus_id in seen_corpus_ids:
            raise ValueError(f"duplicate corpus_id: {corpus_id}")
        seen_corpus_ids.add(corpus_id)

        source = document.get("source")
        if not isinstance(source, Mapping):
            raise ValueError(f"corpus {corpus_id} has invalid source metadata")
        source_id = _text(source.get("id"), "source.id")
        sources.add(source_id)

        cases = document.get("cases")
        assert isinstance(cases, list)
        total_cases += len(cases)
        for case in cases:
            if not isinstance(case, Mapping):
                continue
            repository = str(case.get("repository_id") or "").strip()
            if repository:
                repositories.add(repository)
            language = str(case.get("language") or "unknown").strip().lower()
            language = language or "unknown"
            languages[language] = languages.get(language, 0) + 1

        corpus_reports.append(
            {
                "corpus_id": corpus_id,
                "source_id": source_id,
                "summary": summary,
            }
        )

    blockers: list[str] = []
    for source_id in required_sources:
        if source_id not in sources:
            blockers.append(f"missing_source:{source_id}")
    known_languages = {language for language in languages if language != "unknown"}
    if len(known_languages) < minimum_languages:
        blockers.append(
            f"language_diversity:{len(known_languages)}<{minimum_languages}"
        )
    if not total_cases:
        blockers.append("no_cases")

    return {
        "ready": not blockers,
        "sources": sorted(sources),
        "corpora": sorted(corpus_reports, key=lambda row: row["corpus_id"]),
        "cases": total_cases,
        "repositories": len(repositories),
        "languages": dict(sorted(languages.items())),
        "minimum_languages": minimum_languages,
        "blockers": blockers,
    }
