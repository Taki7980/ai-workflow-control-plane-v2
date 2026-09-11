from __future__ import annotations

import sqlite3
from typing import Any

WAL_RESET_BUG_REFERENCE = "https://www.sqlite.org/wal.html#walreset"
WITHDRAWN_SQLITE_VERSIONS = {(3, 52, 0)}


def parse_sqlite_version(value: str) -> tuple[int, int, int]:
    parts = str(value).strip().split(".")
    if len(parts) < 3:
        raise ValueError(f"invalid SQLite version: {value!r}")
    try:
        return tuple(int(part) for part in parts[:3])  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"invalid SQLite version: {value!r}") from exc


def sqlite_wal_runtime_status(
    version: str | None = None,
) -> dict[str, Any]:
    raw = sqlite3.sqlite_version if version is None else str(version)
    try:
        parsed = parse_sqlite_version(raw)
    except ValueError:
        return {
            "version": raw,
            "parsed_version": None,
            "safe_for_wal": False,
            "reason": "unparseable_sqlite_version",
            "reference": WAL_RESET_BUG_REFERENCE,
        }

    safe = False
    reason = "wal_reset_bug_affected_range"
    if parsed in WITHDRAWN_SQLITE_VERSIONS:
        reason = "withdrawn_sqlite_3_52_0"
    elif parsed[:2] == (3, 44) and parsed[2] >= 6:
        safe = True
        reason = "patched_3_44_backport"
    elif parsed[:2] == (3, 50) and parsed[2] >= 7:
        safe = True
        reason = "patched_3_50_backport"
    elif parsed[:2] == (3, 51) and parsed[2] >= 3:
        safe = True
        reason = "patched_3_51_release"
    elif parsed[0] > 3 or (parsed[0] == 3 and parsed[1] >= 53):
        safe = True
        reason = "post_fix_release"

    return {
        "version": raw,
        "parsed_version": list(parsed),
        "safe_for_wal": safe,
        "reason": reason,
        "reference": WAL_RESET_BUG_REFERENCE,
    }


def require_safe_sqlite_wal_runtime(
    version: str | None = None,
) -> dict[str, Any]:
    status = sqlite_wal_runtime_status(version)
    if not status["safe_for_wal"]:
        raise RuntimeError(
            "SQLite WAL production mirror requires a runtime containing the "
            "WAL-reset corruption fix. Detected SQLite "
            f"{status['version']} ({status['reason']}). "
            "Use SQLite 3.51.3+, 3.50.7, 3.44.6, or a later fixed release. "
            f"See {WAL_RESET_BUG_REFERENCE}"
        )
    return status
