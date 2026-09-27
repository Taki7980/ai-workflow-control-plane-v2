from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .code_review_graph import workspace_graph_fingerprint
from .io_utils import atomic_create_json
from .provenance import config_digest
from .workspace_state import (
    aggregate_workspace_fingerprint,
    workspace_fingerprint,
)


JOURNAL_RELATIVE = Path("ai-workspace/generated/run-journal")
REPLAY_SCHEMA_VERSION = "ai-workflow-run-journal-v2"
REPLAY_MODE = "decision-history-only"
JOURNAL_DIGEST_FIELD = "journal_digest"
EXPECTED_REPLAY_EVENT_KINDS = (
    "routing",
    "repository_routing",
    "retrieval",
    "ranking",
    "selection",
    "orchestration",
    "authorization",
)
_MAX_CHANGED_FILES = 4096
_MAX_CHANGED_FILE_CHARS = 4096
_MAX_JOURNAL_BYTES = 8 * 1024 * 1024


def _safe_run_id(run_id: str) -> str:
    value = str(run_id).strip()
    safe = "".join(
        char for char in value if char.isalnum() or char in "-_"
    )
    if not value or safe != value:
        raise ValueError("invalid run_id")
    return value


def _journal_path(root: Path, run_id: str) -> Path:
    return Path(root).resolve() / JOURNAL_RELATIVE / (
        _safe_run_id(run_id) + ".json"
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical(value).decode("utf-8"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _journal_digest(record: Mapping[str, Any]) -> str:
    payload = {
        str(key): value
        for key, value in record.items()
        if str(key) != JOURNAL_DIGEST_FIELD
    }
    return _sha256(payload)


def _validated_changed_files(
    record: Mapping[str, Any],
    *,
    required: bool = True,
) -> list[str]:
    raw = record.get("changed_files")
    if raw is None and not required:
        return []
    if not isinstance(raw, list):
        raise ValueError("changed_files must be a list")
    if len(raw) > _MAX_CHANGED_FILES:
        raise ValueError("changed_files exceeds replay safety bound")

    changed: list[str] = []
    for item in raw:
        if (
            not isinstance(item, str)
            or not item
            or "\x00" in item
            or len(item) > _MAX_CHANGED_FILE_CHARS
        ):
            raise ValueError("changed_files contains an invalid path")
        changed.append(item)
    return changed


def chain_replay_events(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Bind ordered replay events into a tamper-evident hash chain."""

    chained: list[dict[str, Any]] = []
    previous: str | None = None
    for sequence, raw in enumerate(events):
        kind = str(raw.get("kind") or "").strip()
        payload = raw.get("payload")
        if not kind:
            raise ValueError("replay event kind must not be blank")
        if not isinstance(payload, Mapping):
            raise ValueError("replay event payload must be an object")
        body = {
            "sequence": sequence,
            "kind": kind,
            "previous_event_digest": previous,
            "payload": _json_clone(dict(payload)),
        }
        digest = _sha256(body)
        chained.append({**body, "event_digest": digest})
        previous = digest
    return chained


def build_replay_journal(
    record: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one self-contained replay record without raw task/evidence text."""

    run_id = _safe_run_id(str(record.get("run_id") or ""))
    normalized = _json_clone(dict(record))
    required_mappings = (
        "policy_identity",
        "workspace_state",
        "graph_state",
        "repository_state",
        "provider_versions",
        "retrieval",
    )
    for key in required_mappings:
        if not isinstance(normalized.get(key), dict):
            raise ValueError(f"{key} must be an object")
    if not isinstance(normalized.get("selected_evidence"), list):
        raise ValueError("selected_evidence must be a list")
    _validated_changed_files(normalized)

    kinds = tuple(str(event.get("kind") or "").strip() for event in events)
    if kinds != EXPECTED_REPLAY_EVENT_KINDS:
        raise ValueError(
            "replay events must match the v2 event contract exactly"
        )

    chained = chain_replay_events(events)
    journal: dict[str, Any] = {
        **normalized,
        "schema_version": REPLAY_SCHEMA_VERSION,
        "replay_mode": REPLAY_MODE,
        "run_id": run_id,
        "replay_event_count": len(chained),
        "replay_head_digest": chained[-1]["event_digest"],
        "replay_events": chained,
    }
    journal[JOURNAL_DIGEST_FIELD] = _journal_digest(journal)
    return journal


def verify_replay_journal(
    record: Mapping[str, Any],
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if record.get("schema_version") != REPLAY_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if record.get("replay_mode") != REPLAY_MODE:
        errors.append("replay_mode_mismatch")

    raw_run_id = record.get("run_id")
    try:
        recorded_run_id = (
            _safe_run_id(raw_run_id)
            if isinstance(raw_run_id, str)
            else ""
        )
    except ValueError:
        recorded_run_id = ""
    if not recorded_run_id:
        errors.append("run_id_invalid")
    if expected_run_id is not None:
        try:
            requested_run_id = _safe_run_id(expected_run_id)
        except ValueError:
            requested_run_id = ""
            errors.append("expected_run_id_invalid")
        if recorded_run_id != requested_run_id:
            errors.append("run_id_mismatch")

    for key in (
        "policy_identity",
        "workspace_state",
        "graph_state",
        "repository_state",
        "provider_versions",
        "retrieval",
    ):
        if not isinstance(record.get(key), Mapping):
            errors.append(f"{key}_invalid")
    if not isinstance(record.get("selected_evidence"), list):
        errors.append("selected_evidence_invalid")
    try:
        _validated_changed_files(record)
    except ValueError:
        errors.append("changed_files_invalid")

    raw_events = record.get("replay_events")
    if not isinstance(raw_events, list):
        return {
            "valid": False,
            "errors": [*errors, "replay_events_missing"],
            "event_count": 0,
            "head_digest": None,
            "journal_digest": record.get(JOURNAL_DIGEST_FIELD),
        }

    if len(raw_events) != len(EXPECTED_REPLAY_EVENT_KINDS):
        errors.append("event_contract_count_mismatch")

    previous: str | None = None
    event_payloads: dict[str, Mapping[str, Any]] = {}
    for sequence, raw in enumerate(raw_events):
        if not isinstance(raw, Mapping):
            errors.append(f"event_{sequence}_invalid")
            continue
        if raw.get("sequence") != sequence:
            errors.append(f"event_{sequence}_sequence_mismatch")

        kind = str(raw.get("kind") or "").strip()
        payload = raw.get("payload")
        expected_kind = (
            EXPECTED_REPLAY_EVENT_KINDS[sequence]
            if sequence < len(EXPECTED_REPLAY_EVENT_KINDS)
            else None
        )
        if expected_kind is not None and kind != expected_kind:
            errors.append(f"event_{sequence}_kind_mismatch")
        if not kind or not isinstance(payload, Mapping):
            errors.append(f"event_{sequence}_shape_invalid")
            continue
        event_payloads[kind] = payload

        stored_previous = raw.get("previous_event_digest")
        if stored_previous != previous:
            errors.append(f"event_{sequence}_previous_digest_mismatch")
        body = {
            "sequence": sequence,
            "kind": kind,
            "previous_event_digest": stored_previous,
            "payload": dict(payload),
        }
        try:
            expected_digest = _sha256(body)
        except (TypeError, ValueError):
            errors.append(f"event_{sequence}_digest_unverifiable")
            expected_digest = ""
        supplied = str(raw.get("event_digest") or "")
        if supplied != expected_digest:
            errors.append(f"event_{sequence}_digest_mismatch")
        previous = supplied

    if record.get("replay_event_count") != len(raw_events):
        errors.append("event_count_mismatch")
    if record.get("replay_head_digest") != previous:
        errors.append("head_digest_mismatch")

    retrieval_payload = event_payloads.get("retrieval")
    recorded_retrieval = record.get("retrieval")
    if (
        isinstance(retrieval_payload, Mapping)
        and isinstance(recorded_retrieval, Mapping)
        and dict(retrieval_payload) != dict(recorded_retrieval)
    ):
        errors.append("retrieval_snapshot_mismatch")

    selection_payload = event_payloads.get("selection")
    if isinstance(selection_payload, Mapping):
        if selection_payload.get("selected_evidence") != record.get(
            "selected_evidence"
        ):
            errors.append("selection_snapshot_mismatch")

    supplied_journal_digest = str(
        record.get(JOURNAL_DIGEST_FIELD) or ""
    )
    try:
        expected_journal_digest = _journal_digest(record)
    except (TypeError, ValueError):
        expected_journal_digest = ""
        errors.append("journal_digest_unverifiable")
    if supplied_journal_digest != expected_journal_digest:
        errors.append("journal_digest_mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "event_count": len(raw_events),
        "head_digest": previous,
        "journal_digest": supplied_journal_digest or None,
    }


def write_run_journal(root: Path, record: Mapping[str, Any]) -> str:
    run_id = _safe_run_id(str(record.get("run_id") or ""))
    path = _journal_path(root, run_id)
    atomic_create_json(path, dict(record), sort_keys=True)
    return path.relative_to(Path(root).resolve()).as_posix()


def read_run_journal(root: Path, run_id: str) -> dict[str, Any] | None:
    try:
        path = _journal_path(root, run_id)
        if path.stat().st_size > _MAX_JOURNAL_BYTES:
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        OSError,
        RecursionError,
        ValueError,
    ):
        return None
    return raw if isinstance(raw, dict) else None


def _compatibility_from_record(
    root: Path,
    run_id: str,
    config: dict[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        changed_files = _validated_changed_files(
            record,
            required=record.get("schema_version") == REPLAY_SCHEMA_VERSION,
        )
    except ValueError:
        return {
            "run_id": run_id,
            "compatible": False,
            "mismatches": ["invalid_changed_files"],
            "recorded": {},
            "current": {},
        }

    policy = record.get("policy_identity")
    recorded_policy = policy if isinstance(policy, Mapping) else {}
    workspace = record.get("workspace_state")
    recorded_workspace = (
        workspace if isinstance(workspace, Mapping) else {}
    )
    graph = record.get("graph_state")
    recorded_graph = graph if isinstance(graph, Mapping) else {}
    repository = record.get("repository_state")
    recorded_repository = (
        repository if isinstance(repository, Mapping) else {}
    )

    current_workspace = workspace_fingerprint(root, changed_files)
    current_graph = workspace_graph_fingerprint(root, config)
    current = {
        "config_digest": config_digest(config),
        "retrieval_policy_version": str(
            config.get("version", "unknown")
        ),
        "workspace_fingerprint": str(
            current_workspace.get("fingerprint", "")
        ),
        "graph_fingerprint": str(
            current_graph.get("fingerprint", "")
        ),
    }
    recorded = {
        "config_digest": str(
            recorded_policy.get("config_digest", "")
        ),
        "retrieval_policy_version": str(
            recorded_policy.get("retrieval_policy_version", "")
        ),
        "workspace_fingerprint": str(
            recorded_workspace.get("fingerprint", "")
        ),
        "graph_fingerprint": str(
            recorded_graph.get("fingerprint", "")
        ),
    }

    recorded_repository_fingerprint = str(
        recorded_repository.get("fingerprint", "")
    )
    if recorded_repository_fingerprint:
        current_repository = aggregate_workspace_fingerprint(root, config)
        current["repository_fingerprint"] = str(
            current_repository.get("fingerprint", "")
        )
        recorded["repository_fingerprint"] = recorded_repository_fingerprint

    mismatches = [
        name
        for name in current
        if current[name] != recorded[name]
    ]
    return {
        "run_id": run_id,
        "compatible": not mismatches,
        "mismatches": mismatches,
        "recorded": recorded,
        "current": current,
    }


def verify_run_journal(
    root: Path,
    run_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    record = read_run_journal(root, run_id)
    if record is None:
        return {
            "run_id": run_id,
            "compatible": False,
            "mismatches": ["missing_journal"],
        }
    if record.get("schema_version") == REPLAY_SCHEMA_VERSION:
        integrity = verify_replay_journal(
            record,
            expected_run_id=run_id,
        )
        if not integrity["valid"]:
            return {
                "run_id": run_id,
                "compatible": False,
                "mismatches": ["invalid_journal"],
                "recorded": {},
                "current": {},
            }
    return _compatibility_from_record(root, run_id, config, record)


def replay_run_journal(
    root: Path,
    run_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct verified decisions without executing external effects."""

    record = read_run_journal(root, run_id)
    if record is None:
        return {
            "run_id": run_id,
            "found": False,
            "schema_version": None,
            "replay_mode": None,
            "read_only": True,
            "external_execution_performed": False,
            "integrity": {
                "valid": False,
                "errors": ["missing_journal"],
                "event_count": 0,
                "head_digest": None,
                "journal_digest": None,
            },
            "compatibility": {
                "run_id": run_id,
                "compatible": False,
                "mismatches": ["missing_journal"],
            },
            "events_released": False,
            "events": [],
        }

    integrity = verify_replay_journal(
        record,
        expected_run_id=run_id,
    )
    if integrity["valid"]:
        compatibility = _compatibility_from_record(
            root,
            run_id,
            config,
            record,
        )
        raw_events = record.get("replay_events")
        events = [
            dict(item)
            for item in raw_events
            if isinstance(item, Mapping)
        ]
        events_released = True
    else:
        compatibility = {
            "run_id": run_id,
            "compatible": False,
            "mismatches": ["invalid_journal"],
            "recorded": {},
            "current": {},
        }
        events = []
        events_released = False

    return {
        "run_id": run_id,
        "found": True,
        "schema_version": record.get("schema_version"),
        "replay_mode": record.get("replay_mode"),
        "read_only": True,
        "external_execution_performed": False,
        "integrity": integrity,
        "compatibility": compatibility,
        "replay_head_digest": record.get("replay_head_digest"),
        "journal_digest": record.get(JOURNAL_DIGEST_FIELD),
        "events_released": events_released,
        "events": events,
    }
