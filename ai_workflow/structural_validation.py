from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .models import ContextItem
from .path_policy import PathOutsideWorkspace, resolve_within_root
from .scip import scip_context, scip_ready


class StructuralEvidenceConfidence(str, Enum):
    """Evidence state for structural claims; never a probability."""

    CANDIDATE = "candidate"
    CORROBORATED = "corroborated"
    VERIFIED = "verified"


_PATH_KEYS = ("file_path", "relative_path", "path")
_NAME_KEYS = ("name", "qualified_name", "parent_name", "import_target")


def _rows(item: ContextItem) -> list[Mapping[str, Any]]:
    try:
        payload = json.loads(item.text)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    raw = payload.get("results")
    if not isinstance(raw, list):
        raw = payload.get("impacted_nodes")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, Mapping)]


def _row_path(row: Mapping[str, Any]) -> str:
    for key in _PATH_KEYS:
        value = str(row.get(key) or "").strip().replace("\\", "/")
        if value:
            return value
    return ""


def _row_names(row: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in _NAME_KEYS:
        value = str(row.get(key) or "").strip()
        if value:
            names.add(value)
            tail = value.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
            if tail:
                names.add(tail)
    return names


def _source_confirms(root: Path, row: Mapping[str, Any]) -> bool:
    relative = _row_path(row)
    if not relative:
        return False
    try:
        path = resolve_within_root(root, relative)
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
    except (PathOutsideWorkspace, OSError):
        return False
    names = {name for name in _row_names(row) if len(name) >= 2}
    return bool(names and any(name in text for name in names))


def _scip_keys(items: list[ContextItem]) -> tuple[set[str], set[str]]:
    paths: set[str] = set()
    names: set[str] = set()
    for item in items:
        path = str(item.metadata.get("path") or "").replace("\\", "/")
        if path:
            paths.add(path.casefold())
        for key in ("symbol_name", "symbol"):
            value = str(item.metadata.get(key) or "").strip()
            if value:
                names.add(value.casefold())
                names.add(value.rsplit(".", 1)[-1].rsplit("::", 1)[-1].casefold())
    return paths, names


def _scip_confirms(
    row: Mapping[str, Any],
    *,
    scip_paths: set[str],
    scip_names: set[str],
) -> bool:
    path = _row_path(row).casefold()
    names = {name.casefold() for name in _row_names(row)}
    path_match = bool(path and path in scip_paths)
    name_match = bool(names & scip_names)
    return path_match and name_match


def validate_crg_item(
    root: Path,
    item: ContextItem,
    *,
    query: str,
    symbol: str | None,
    changed_files: list[str] | None,
    limit: int,
) -> ContextItem:
    """Differentially validate a CRG item against source and, when ready, SCIP.

    Confidence is categorical. It is intentionally not exposed as a probability.
    Non-empty CRG output starts as candidate; one independent oracle promotes it
    to corroborated and agreement from source + SCIP promotes it to verified.
    """

    if item.source != "code_review_graph":
        return item

    metadata = dict(item.metadata)
    rows = _rows(item)
    if not rows:
        if metadata.get("empty_verified"):
            metadata.update(
                {
                    "evidence_confidence": StructuralEvidenceConfidence.CORROBORATED.value,
                    "confidence_basis": ["crg_verified_empty"],
                    "structural_valid": True,
                    "high_risk_eligible": False,
                }
            )
        else:
            metadata.update(
                {
                    "evidence_confidence": StructuralEvidenceConfidence.CANDIDATE.value,
                    "confidence_basis": [],
                    "structural_valid": False,
                    "high_risk_eligible": False,
                }
            )
        return ContextItem(
            item.source, item.text, item.score, item.stale, metadata, dict(item.provenance)
        )

    source_hits = {_row_path(row) for row in rows if _source_confirms(root, row)}
    source_hits.discard("")

    scip_items: list[ContextItem] = []
    try:
        if scip_ready(root, root):
            pattern = str(metadata.get("pattern") or "")
            scip_items = scip_context(
                root,
                query,
                symbol or str(metadata.get("anchor") or "") or None,
                changed_files,
                max(limit, len(rows)),
                patterns=(pattern,) if pattern else (),
            )
    except (OSError, ValueError):
        scip_items = []
    scip_paths, scip_names = _scip_keys(scip_items)

    source_confirmed = 0
    scip_confirmed = 0
    doubly_confirmed = 0
    for row in rows:
        source_ok = _row_path(row) in source_hits
        scip_ok = _scip_confirms(row, scip_paths=scip_paths, scip_names=scip_names)
        source_confirmed += int(source_ok)
        scip_confirmed += int(scip_ok)
        doubly_confirmed += int(source_ok and scip_ok)

    basis: list[str] = []
    if source_confirmed:
        basis.append("source")
    if scip_confirmed:
        basis.append("scip")

    if doubly_confirmed:
        confidence = StructuralEvidenceConfidence.VERIFIED
    elif source_confirmed or scip_confirmed:
        confidence = StructuralEvidenceConfidence.CORROBORATED
    else:
        confidence = StructuralEvidenceConfidence.CANDIDATE

    metadata.update(
        {
            "evidence_confidence": confidence.value,
            "confidence_basis": basis,
            "source_confirmed_results": source_confirmed,
            "scip_confirmed_results": scip_confirmed,
            "verified_results": doubly_confirmed,
            "structural_valid": confidence is not StructuralEvidenceConfidence.CANDIDATE,
            # High-risk consumers must have at least one independent oracle.
            "high_risk_eligible": confidence in {
                StructuralEvidenceConfidence.CORROBORATED,
                StructuralEvidenceConfidence.VERIFIED,
            },
        }
    )
    return ContextItem(
        item.source, item.text, item.score, item.stale, metadata, dict(item.provenance)
    )


def validate_crg_items(
    root: Path,
    items: list[ContextItem],
    *,
    query: str,
    symbol: str | None,
    changed_files: list[str] | None,
    limit: int,
) -> list[ContextItem]:
    return [
        validate_crg_item(
            root,
            item,
            query=query,
            symbol=symbol,
            changed_files=changed_files,
            limit=limit,
        )
        for item in items
    ]
