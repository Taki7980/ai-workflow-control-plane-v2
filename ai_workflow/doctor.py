from __future__ import annotations
import sys
from pathlib import Path
from .code_review_graph import workspace_health
from .providers import detect
from .indexer import load_state, sha256
from .handoff import validate as validate_handoff
from .sqlite_runtime import sqlite_wal_runtime_status

DOCTOR_SCHEMA_VERSION = 1


def run(root: Path, config: dict) -> tuple[dict, bool]:
    status = detect(root, config)
    state = load_state(root)
    stale = 0
    for rel, meta in state.get("files", {}).items():
        p = root / rel
        try:
            if not p.exists() or sha256(p) != meta.get("sha256"):
                stale += 1
        except OSError:
            stale += 1
    handoff_path = root / "ai-workspace" / "handoff" / "HANDOFF.md"
    handoff_present = handoff_path.exists()
    handoff_errors = validate_handoff(root, int(config["handoff"].get("max_lines", 30))) if handoff_present else []
    tracked = len(state.get("files", {}))
    recommendations = []
    if not state:
        recommendations.append("Local index not built; run `ai-workflow index`")
    crg_health = workspace_health(root, config, timeout=5)
    crg_installed = bool(crg_health.get("installed"))
    min_crg = int(config.get("context", {}).get("crg", {}).get("min_source_files", 250))
    if tracked >= min_crg and not crg_installed:
        recommendations.append(
            f"repository index has {tracked} source files; install Code Review Graph "
            "for structural Full-lane work"
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
        recommendations.append("Superpowers not detected; Full lane will use native Plan -> Build -> Review")
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
        and bool(state)
        and not handoff_errors
        and stale == 0
        and (not production_enabled or sqlite_wal["safe_for_wal"])
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
        "index": {"present": bool(state), "tracked_files": tracked, "stale_files": stale},
        "handoff_errors": handoff_errors,
        "recommendations": recommendations,
        "exit_codes": {"ok": 0, "strict_failure": 1},
    }
    return result, core_ok
