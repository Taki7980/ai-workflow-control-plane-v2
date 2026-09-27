from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .code_review_graph import workspace_graph_fingerprint
from .io_utils import atomic_create_json
from .provenance import config_digest
from .workspace_state import workspace_fingerprint


JOURNAL_RELATIVE = Path("ai-workspace/generated/run-journal")
REPLAY_SCHEMA_VERSION = "ai-workflow-run-journal-v2"
REPLAY_MODE = "decision-history-only"


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
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


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
            "payload": dict(payload),
        }
        digest = _sha256(body)
        chained.append({**body, "event_digest": digest})
        previous = digest
    return chained


def build_replay_journal(
    record: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Add replay metadata without introducing raw task/evidence content."""

    run_id = _safe_run_id(str(record.get("run_id") or ""))
    chained = chain_replay_events(events)
    return {
        **dict(record),
        "schema_version": REPLAY_SCHEMA_VERSION,
        "replay_mode": REPLAY_MODE,
        "run_id": run_id,
        "replay_event_count": len(chained),
        "replay_head_digest": (
            chained[-1]["event_digest"] if chained else None
        ),
        "replay_events": chained,
    }


def verify_replay_journal(record: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if record.get("schema_version") != REPLAY_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if record.get("replay_mode") != REPLAY_MODE:
        errors.append("replay_mode_mismatch")

    raw_events = record.get("replay_events")
    if not isinstance(raw_events, list):
        return {
            "valid": False,
            "errors": [*errors, "replay_events_missing"],
            "event_count": 0,
            "head_digest": None,
        }

    previous: str | None = None
    for sequence, raw in enumerate(raw_events):
        if not isinstance(raw, Mapping):
            errors.append(f"event_{sequence}_invalid")
            continue
        if raw.get("sequence") != sequence:
            errors.append(f"event_{sequence}_sequence_mismatch")
        kind = str(raw.get("kind") or "").strip()
        payload = raw.get("payload")
        if not kind or not isinstance(payload, Mapping):
            errors.append(f"event_{sequence}_shape_invalid")
            continue
        if raw.get("previous_event_digest") != previous:
            errors.append(f"event_{sequence}_previous_digest_mismatch")
        body = {
            "sequence": sequence,
            "kind": kind,
            "previous_event_digest": previous,
            "payload": dict(payload),
        }
        expected = _sha256(body)
        supplied = str(raw.get("event_digest") or "")
        if supplied != expected:
            errors.append(f"event_{sequence}_digest_mismatch")
        previous = supplied

    if record.get("replay_event_count") != len(raw_events):
        errors.append("event_count_mismatch")
    if record.get("replay_head_digest") != previous:
        errors.append("head_digest_mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "event_count": len(raw_events),
        "head_digest": previous,
    }


def write_run_journal(root: Path, record: Mapping[str, Any]) -> str:
    run_id = _safe_run_id(str(record.get("run_id") or ""))
    path = _journal_path(root, run_id)
    atomic_create_json(path, dict(record), sort_keys=True)
    return path.relative_to(Path(root).resolve()).as_posix()


def read_run_journal(root: Path, run_id: str) -> dict[str, Any] | None:
    try:
        raw = json.loads(
            _journal_path(root, run_id).read_text(encoding="utf-8")
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None
    return raw if isinstance(raw, dict) else None


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

    policy = record.get("policy_identity")
    recorded_policy = policy if isinstance(policy, Mapping) else {}
    workspace = record.get("workspace_state")
    recorded_workspace = (
        workspace if isinstance(workspace, Mapping) else {}
    )
    graph = record.get("graph_state")
    recorded_graph = graph if isinstance(graph, Mapping) else {}

    changed_files_raw = record.get("changed_files")
    changed_files = (
        [str(item) for item in changed_files_raw]
        if isinstance(changed_files_raw, list)
        else []
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


def replay_run_journal(
    root: Path,
    run_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Reconstruct recorded control-plane decisions without executing effects."""

    record = read_run_journal(root, run_id)
    if record is None:
        return {
            "run_id": run_id,
            "found": False,
            "replay_mode": REPLAY_MODE,
            "read_only": True,
            "external_execution_performed": False,
            "integrity": {
                "valid": False,
                "errors": ["missing_journal"],
                "event_count": 0,
                "head_digest": None,
            },
            "compatibility": {
                "run_id": run_id,
                "compatible": False,
                "mismatches": ["missing_journal"],
            },
            "events": [],
        }

    integrity = verify_replay_journal(record)
    compatibility = verify_run_journal(root, run_id, config)
    raw_events = record.get("replay_events")
    events = (
        [dict(item) for item in raw_events if isinstance(item, Mapping)]
        if isinstance(raw_events, list)
        else []
    )
    return {
        "run_id": run_id,
        "found": True,
        "schema_version": record.get("schema_version"),
        "replay_mode": record.get("replay_mode", REPLAY_MODE),
        "read_only": True,
        "external_execution_performed": False,
        "integrity": integrity,
        "compatibility": compatibility,
        "replay_head_digest": record.get("replay_head_digest"),
        "events": events,
    }
