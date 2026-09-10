from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .execution_semantics import ProviderSemantics, cache_eligible
from .io_utils import atomic_write_json
from .models import ContextItem
from .retrieval_contracts import ProviderResult, RetrievalRequest


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        canonical = [_canonical(item) for item in value]
        return sorted(
            canonical,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def retrieval_cache_key(
    retrieval_policy_version: str,
    workspace_fingerprint: str,
    provider_name: str,
    provider_version: str,
    request: RetrievalRequest,
) -> str:
    """Build a path-independent cache key from deterministic run inputs."""

    payload = {
        "schema_version": 1,
        "retrieval_policy_version": str(retrieval_policy_version),
        "workspace_fingerprint": str(workspace_fingerprint),
        "provider": {
            "name": str(provider_name),
            "version": str(provider_version),
        },
        "request": {
            "query": request.query,
            "limit": int(request.limit),
            "intent": request.intent,
            "timeout_seconds": float(request.timeout_seconds),
            "changed_files": list(request.changed_files),
            "metadata": _canonical(request.metadata),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_to_dict(result: ProviderResult) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": result.provider,
        "items": [item.to_dict() for item in result.items],
        "latency_ms": float(result.latency_ms),
        "error": result.error,
        "error_kind": result.error_kind,
        "timed_out": bool(result.timed_out),
        "output_limited": bool(result.output_limited),
        "returncode": result.returncode,
    }


def _result_from_dict(raw: Mapping[str, Any]) -> ProviderResult:
    items: list[ContextItem] = []
    raw_items = raw.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            metadata_raw = item.get("metadata")
            provenance_raw = item.get("provenance")
            metadata = (
                dict(metadata_raw)
                if isinstance(metadata_raw, Mapping)
                else {}
            )
            provenance = (
                dict(provenance_raw)
                if isinstance(provenance_raw, Mapping)
                else {}
            )
            items.append(
                ContextItem(
                    source=str(item.get("source", "cache")),
                    text=str(item.get("text", "")),
                    score=float(item.get("score", 0.0) or 0.0),
                    stale=bool(item.get("stale", False)),
                    metadata=metadata,
                    provenance=provenance,
                )
            )
    return ProviderResult(
        provider=str(raw.get("provider", "unknown")),
        items=tuple(items),
        latency_ms=float(raw.get("latency_ms", 0.0) or 0.0),
        error=(
            str(raw["error"])
            if raw.get("error") is not None
            else None
        ),
        error_kind=(
            str(raw["error_kind"])
            if raw.get("error_kind") is not None
            else None
        ),
        timed_out=bool(raw.get("timed_out", False)),
        output_limited=bool(raw.get("output_limited", False)),
        returncode=(
            int(raw["returncode"])
            if raw.get("returncode") is not None
            else None
        ),
    )


class FileRetrievalCache:
    """Opt-in local cache for explicitly cache-safe provider results."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, key: str) -> Path:
        valid = key and all(
            char in "0123456789abcdefABCDEF-_" for char in key
        )
        safe_key = (
            key
            if valid
            else hashlib.sha256(str(key).encode("utf-8")).hexdigest()
        )
        return self.directory / f"{safe_key}.json"

    def get(self, key: str) -> ProviderResult | None:
        try:
            raw = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
            return None
        try:
            result = _result_from_dict(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if result.ok else None

    def put(
        self,
        key: str,
        result: ProviderResult,
        semantics: ProviderSemantics,
    ) -> bool:
        if not result.ok or not cache_eligible(semantics):
            return False
        atomic_write_json(
            self._path(key),
            _result_to_dict(result),
            sort_keys=True,
        )
        return True
