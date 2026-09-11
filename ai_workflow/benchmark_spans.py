from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .benchmark_protocol import (
    context_item_file,
    context_item_repository,
    normalize_file_path,
)
from .models import ContextItem


_LINE_KEYS = ("line", "line_number", "start_line", "line_start")
_END_LINE_KEYS = ("end_line", "line_end")


@dataclass(frozen=True)
class GoldSpan:
    path: str
    start_line: int
    end_line: int
    repository_id: str | None = None
    content_sha256: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GoldSpan":
        path = normalize_file_path(str(value.get("path", "")))
        if not path:
            raise ValueError("gold span path must not be blank")
        start = int(value.get("start_line", 0))
        end = int(value.get("end_line", 0))
        if start < 1 or end < start:
            raise ValueError("gold span lines must satisfy 1 <= start <= end")
        repository_raw = value.get("repository_id")
        repository_id = (
            str(repository_raw).strip()
            if repository_raw is not None and str(repository_raw).strip()
            else None
        )
        digest_raw = value.get("content_sha256")
        digest = (
            str(digest_raw).strip().lower()
            if digest_raw is not None and str(digest_raw).strip()
            else None
        )
        if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("gold span content_sha256 must be 64 lowercase hex")
        return cls(
            path=path,
            start_line=start,
            end_line=end,
            repository_id=repository_id,
            content_sha256=digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "repository_id": self.repository_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class RetrievedSpan:
    path: str
    start_line: int
    end_line: int
    repository_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "repository_id": self.repository_id,
        }


def _line_value(container: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        raw = container.get(key)
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value >= 1:
            return value
    return None


def context_item_span(item: ContextItem) -> RetrievedSpan | None:
    path = context_item_file(item)
    if path is None:
        return None
    start: int | None = None
    end: int | None = None
    for container in (item.metadata, item.provenance):
        if not isinstance(container, dict):
            continue
        if start is None:
            start = _line_value(container, _LINE_KEYS)
        if end is None:
            end = _line_value(container, _END_LINE_KEYS)

    match = re.match(
        r"^(?P<path>.+?):(?P<start>\d+)(?::(?P<end>\d+))?:\s",
        item.text,
    )
    if match:
        if start is None:
            start = int(match.group("start"))
        if end is None and match.group("end"):
            end = int(match.group("end"))

    if start is None:
        return None
    if end is None:
        end = start
    if end < start:
        end = start
    return RetrievedSpan(
        path=path,
        start_line=start,
        end_line=end,
        repository_id=context_item_repository(item),
    )


def normalize_gold_spans(values: list[dict[str, Any]]) -> list[GoldSpan]:
    spans = [GoldSpan.from_dict(value) for value in values]
    seen: set[tuple[str | None, str, int, int]] = set()
    unique: list[GoldSpan] = []
    for span in spans:
        key = (
            span.repository_id,
            span.path,
            span.start_line,
            span.end_line,
        )
        if key not in seen:
            seen.add(key)
            unique.append(span)
    return unique


def _same_location(retrieved: RetrievedSpan, gold: GoldSpan) -> bool:
    if retrieved.path != gold.path:
        return False
    if (
        gold.repository_id is not None
        and retrieved.repository_id != gold.repository_id
    ):
        return False
    return True


def _overlap(
    retrieved: RetrievedSpan,
    gold: GoldSpan,
) -> tuple[int, int] | None:
    if not _same_location(retrieved, gold):
        return None
    start = max(retrieved.start_line, gold.start_line)
    end = min(retrieved.end_line, gold.end_line)
    return (start, end) if start <= end else None


def _covered_lines(
    gold: GoldSpan,
    retrieved: list[RetrievedSpan],
) -> int:
    intervals = [
        overlap
        for item in retrieved
        if (overlap := _overlap(item, gold)) is not None
    ]
    if not intervals:
        return 0
    intervals.sort()
    covered = 0
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= current_end + 1:
            current_end = max(current_end, end)
            continue
        covered += current_end - current_start + 1
        current_start, current_end = start, end
    covered += current_end - current_start + 1
    return covered


def span_retrieval_metrics(
    items: list[ContextItem],
    gold_spans: list[dict[str, Any]],
    k: int = 5,
) -> dict[str, Any] | None:
    if not gold_spans:
        return None
    gold = normalize_gold_spans(gold_spans)
    cutoff = max(1, int(k))
    ranked: list[RetrievedSpan] = []
    for item in items:
        span = context_item_span(item)
        if span is not None:
            ranked.append(span)
        if len(ranked) >= cutoff:
            break

    hit_flags = [
        any(_overlap(retrieved, span) is not None for span in gold)
        for retrieved in ranked
    ]
    first_hit = next(
        (rank for rank, hit in enumerate(hit_flags, 1) if hit),
        None,
    )
    matched_gold = [
        span
        for span in gold
        if any(_overlap(retrieved, span) is not None for retrieved in ranked)
    ]
    total_gold_lines = sum(
        span.end_line - span.start_line + 1
        for span in gold
    )
    covered_gold_lines = sum(
        _covered_lines(span, ranked)
        for span in gold
    )
    total_retrieved_lines = sum(
        span.end_line - span.start_line + 1
        for span in ranked
    )
    relevant_retrieved_lines = 0
    for retrieved in ranked:
        covered: set[int] = set()
        for span in gold:
            overlap = _overlap(retrieved, span)
            if overlap is None:
                continue
            covered.update(range(overlap[0], overlap[1] + 1))
        relevant_retrieved_lines += len(covered)

    span_precision = sum(hit_flags) / cutoff
    span_recall = len(matched_gold) / len(gold)
    span_f1 = (
        2 * span_precision * span_recall / (span_precision + span_recall)
        if span_precision + span_recall
        else 0.0
    )
    return {
        "k": cutoff,
        "gold_spans": [span.to_dict() for span in gold],
        "retrieved_spans": [span.to_dict() for span in ranked],
        "matched_gold_spans": [span.to_dict() for span in matched_gold],
        "span_precision_at_k": span_precision,
        "span_recall_at_k": span_recall,
        "span_f1": span_f1,
        "line_precision": (
            relevant_retrieved_lines / total_retrieved_lines
            if total_retrieved_lines
            else 0.0
        ),
        "line_recall": (
            covered_gold_lines / total_gold_lines
            if total_gold_lines
            else 0.0
        ),
        "covered_gold_lines": covered_gold_lines,
        "total_gold_lines": total_gold_lines,
        "first_gold_rank": first_hit,
    }
