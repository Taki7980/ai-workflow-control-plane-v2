from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .models import RouteDecision


FEATURE_SCHEMA_VERSION = "retrieval-context-v1"
FEATURE_FIELDS = (
    "lane",
    "risk",
    "intent",
    "query_length_bucket",
    "changed_files_bucket",
    "workspace_roots_bucket",
)
DEFAULT_POLICY_FIELDS = (
    "intent",
    "lane",
    "changed_files_bucket",
)


@dataclass(frozen=True)
class RetrievalContextFeatures:
    lane: str
    risk: str
    intent: str
    query_length_bucket: str
    changed_files_bucket: str
    workspace_roots_bucket: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _query_length_bucket(query: str) -> str:
    count = len(query.split())
    if count <= 4:
        return "1-4"
    if count <= 8:
        return "5-8"
    if count <= 16:
        return "9-16"
    return "17+"


def _count_bucket(count: int) -> str:
    value = max(0, int(count))
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    return "4+"


def _workspace_bucket(count: int) -> str:
    value = max(1, int(count))
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    return "3+"


def build_context_features(
    query: str,
    decision: RouteDecision,
    intent: str,
    *,
    changed_files_count: int = 0,
    workspace_roots_count: int = 1,
) -> RetrievalContextFeatures:
    return RetrievalContextFeatures(
        lane=decision.lane.value,
        risk=decision.risk.value,
        intent=str(intent),
        query_length_bucket=_query_length_bucket(query),
        changed_files_bucket=_count_bucket(changed_files_count),
        workspace_roots_bucket=_workspace_bucket(workspace_roots_count),
    )


def normalize_context_features(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, str] = {}
    for field in FEATURE_FIELDS:
        raw = value.get(field)
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        out[field] = text
    return out


def validate_context_fields(
    fields: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(field).strip() for field in fields))
    if not normalized:
        raise ValueError("at least one context field is required")
    unsupported = [field for field in normalized if field not in FEATURE_FIELDS]
    if unsupported:
        raise ValueError(
            "unsupported context fields: " + ", ".join(sorted(unsupported))
        )
    return normalized


def context_key(
    features: dict[str, str],
    fields: list[str] | tuple[str, ...] = DEFAULT_POLICY_FIELDS,
) -> str:
    selected = validate_context_fields(fields)
    normalized = normalize_context_features(features)
    if normalized is None:
        raise ValueError("context features do not match the current schema")
    payload = {field: normalized[field] for field in selected}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def feature_schema_descriptor() -> dict[str, Any]:
    return {
        "version": FEATURE_SCHEMA_VERSION,
        "fields": list(FEATURE_FIELDS),
        "default_policy_fields": list(DEFAULT_POLICY_FIELDS),
        "stability": (
            "categorical runtime metadata only; no repository content or "
            "task text is stored"
        ),
    }
