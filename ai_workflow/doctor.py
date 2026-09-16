from __future__ import annotations

import sys
from pathlib import Path

from .code_review_graph import workspace_health
from .handoff import validate as validate_handoff
from .indexer import index_data_dir, load_state, sha256
from .providers import detect
from .sqlite_runtime import sqlite_wal_runtime_status
from .workspace import active_repository_roots

DOCTOR_SCHEMA_VERSION = 1


def _repository_relative_path(
    workspace_root: Path,
    repository_root: Path,
) -> str:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    if repository == workspace:
        return "."
    try:
        return repository.relative_to(workspace).as_posix()
    except ValueError:
        return f"legacy:{repository.name}"


def _repository_index_health(
    workspace_root: Path,
    repository_root: Path,
) -> dict:
    repository = Path(repository_root).resolve()
    state = load_state(repository)
    stale = 0
    for relative, metadata in state.get("files", {}).items():
        path = repository / relative
        try:
            if (
                not path.exists()
                or sha256(path) != metadata.get("sha256")
            ):
                stale += 1
        except OSError:
            stale += 1

    return {
        "relative_path": _repository_relative_path(
            workspace_root,
            repository,
        ),
        "repository_root": str(repository),
        "index_dir": str(index_data_dir(repository, workspace_root)),
        "present": bool(state),
        "tracked_files": len(state.get("files", {})),
        "stale_files": stale,
    }


def run(root: Path, config: dict) -> tuple[dict, bool]:
    workspace = Path(root).resolve()
    status = detect(workspace, config)
    repositories = active_repository_roots(workspace, config)
    repository_indexes = [
        _repository_index_health(workspace, repository)
        for repository in repositories
    ]

    indexes_present = bool(repository_indexes) and all(
        row["present"] for row in repository_indexes
    )
    tracked = sum(
        int(row["tracked_files"])
        for row in repository_indexes
    )
    stale = sum(
        int(row["stale_files"])
        for row in repository_indexes
    )

    handoff_path = (
        workspace
        / "ai-workspace"
        / "handoff"
        / "HANDOFF.md"
    )
    handoff_present = handoff_path.exists()
    handoff_errors = (
        validate_handoff(
            workspace,
            int(config["handoff"].get("max_lines", 30)),
        )
        if handoff_present
        else []
    )

    recommendations: list[str] = []
    for row in repository_indexes:
        relative = str(row["relative_path"])
        if not row["present"]:
            recommendations.append(
                "Repository index missing for "
                f"{relative}; run `ai-workflow index`"
            )
        elif row["stale_files"]:
            recommendations.append(
                "Repository index stale for "
                f"{relative} ({row['stale_files']} file(s)); "
                "run `ai-workflow index --incremental`"
            )

    crg_health = workspace_health(
        workspace,
        config,
        timeout=5,
    )
    crg_installed = bool(crg_health.get("installed"))
    min_crg = int(
        config.get("context", {})
        .get("crg", {})
        .get("min_source_files", 250)
    )
    if tracked >= min_crg and not crg_installed:
        recommendations.append(
            f"repository indexes have {tracked} source files; "
            "install Code Review Graph for structural Full-lane work"
        )
    elif (
        crg_installed
        and crg_health.get("repository_count", 0)
        and not crg_health.get("ready")
    ):
        recommendations.append(
            "One or more managed Code Review Graph indexes are not healthy; "
            "rerun `ai-workflow setup` to build/update central graphs"
        )

    if not status.superpowers:
        recommendations.append(
            "Superpowers not detected; Full lane will use native "
            "Plan -> Build -> Review"
        )

    production_cfg = (
        config.get("context", {}).get("production", {})
        if isinstance(config.get("context"), dict)
        else {}
    )
    production_enabled = (
        isinstance(production_cfg, dict)
        and bool(production_cfg.get("enabled", False))
    )
    sqlite_wal = sqlite_wal_runtime_status()
    if production_enabled and not sqlite_wal["safe_for_wal"]:
        recommendations.append(
            "Production WAL mirror is enabled on an SQLite runtime affected "
            "by the WAL-reset corruption bug; upgrade SQLite before use"
        )

    core_ok = (
        config.get("version") == 2
        and indexes_present
        and not handoff_errors
        and stale == 0
        and (
            not production_enabled
            or sqlite_wal["safe_for_wal"]
        )
    )
    optional_capabilities = {
        "ripgrep": bool(status.ripgrep),
        "rtk": bool(status.rtk),
        "superpowers": bool(status.superpowers),
        "code_review_graph": bool(crg_health.get("ready")),
        "semantic_retriever": bool(status.semantic),
    }
    result = {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "core_ok": core_ok,
        "python": sys.version.split()[0],
        "providers": status.to_dict(),
        "optional_capabilities": optional_capabilities,
        "code_review_graph_health": crg_health,
        "config_version": config.get("version"),
        "sqlite_wal_runtime": {
            **sqlite_wal,
            "production_mirror_enabled": production_enabled,
        },
        "index": {
            "present": indexes_present,
            "tracked_files": tracked,
            "stale_files": stale,
        },
        "repository_indexes": repository_indexes,
        "handoff_errors": handoff_errors,
        "recommendations": recommendations,
        "exit_codes": {"ok": 0, "strict_failure": 1},
    }
    return result, core_ok
