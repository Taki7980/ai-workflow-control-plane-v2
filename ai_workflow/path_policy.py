from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any


class PathOutsideWorkspace(ValueError):
    """Raised when an untrusted path escapes its allowed workspace root."""


def resolve_within_root(root: Path, candidate: str | os.PathLike[str]) -> Path:
    """Resolve a user/provider supplied relative path without allowing root escape."""

    root = root.resolve()
    raw = os.fspath(candidate)
    if not raw or "\x00" in raw:
        raise PathOutsideWorkspace("path must be a non-empty relative path")

    path = Path(raw)
    windows = PureWindowsPath(raw)
    if path.is_absolute() or windows.is_absolute() or windows.drive:
        raise PathOutsideWorkspace("absolute paths are not allowed")
    if ".." in path.parts or ".." in windows.parts:
        raise PathOutsideWorkspace("parent traversal is not allowed")

    resolved = (root / path).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathOutsideWorkspace("path escapes the workspace root") from exc
    return resolved


def confine_metadata_paths(root: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unsafe path/file metadata while keeping non-path evidence usable."""

    clean = dict(metadata)
    rejected: list[str] = []
    for key in ("path", "file"):
        if key not in clean:
            continue
        value = clean.get(key)
        if not isinstance(value, (str, os.PathLike)):
            clean.pop(key, None)
            rejected.append(key)
            continue
        try:
            resolve_within_root(root, value)
        except (PathOutsideWorkspace, OSError):
            clean.pop(key, None)
            rejected.append(key)
    if rejected:
        clean["path_rejected"] = True
        clean["rejected_path_fields"] = tuple(rejected)
    return clean
