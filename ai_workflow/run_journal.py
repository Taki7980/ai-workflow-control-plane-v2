from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .code_review_graph import workspace_graph_fingerprint
from .provenance import config_digest
from .workspace_state import workspace_fingerprint


JOURNAL_RELATIVE = Path("ai-workspace/generated/run-journal")


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


def write_run_journal(root: Path, record: Mapping[str, Any]) -> str:
    run_id = _safe_run_id(str(record.get("run_id") or ""))
    path = _journal_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        dict(record),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(payload + "\n")
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
