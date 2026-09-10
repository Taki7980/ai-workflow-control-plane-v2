from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .path_policy import PathOutsideWorkspace, resolve_within_root
from .repository_registry import load_registry, remote_identity, repository_id
from .workspace import workspace_roots


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_json_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _git_bytes(root: Path, *args: str, timeout: int = 5) -> bytes | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _decode_git(value: bytes | None) -> str | None:
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace").strip()
    return text or None


def _git_head(root: Path) -> str | None:
    return _decode_git(_git_bytes(root, "rev-parse", "HEAD", timeout=3))


def _git_ref(root: Path) -> str | None:
    return _decode_git(
        _git_bytes(root, "symbolic-ref", "--quiet", "--short", "HEAD", timeout=3)
    )


def _git_remote_identity(root: Path) -> str | None:
    raw = _decode_git(_git_bytes(root, "config", "--get", "remote.origin.url", timeout=3))
    return remote_identity(raw)


def _stable_index_identity(root: Path) -> dict[str, Any] | None:
    index_path = root / "ai-workspace" / "generated" / "index-state.json"
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = data.get("files")
    if not isinstance(files, dict):
        return None
    return {
        "version": data.get("version"),
        "files": files,
    }


def _changed_file_state(root: Path, changed_files: list[str] | None) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for rel in sorted(set(changed_files or [])):
        try:
            path = resolve_within_root(root, rel)
        except (PathOutsideWorkspace, OSError):
            changed.append({"path": rel, "state": "rejected", "sha256": None})
            continue
        if not path.exists() or not path.is_file():
            changed.append({"path": rel, "state": "missing", "sha256": None})
            continue
        try:
            digest = _sha256_bytes(path.read_bytes())
        except OSError:
            changed.append({"path": rel, "state": "unreadable", "sha256": None})
            continue
        changed.append({"path": rel, "state": "present", "sha256": digest})
    return changed


def _hash_untracked_path(root: Path, rel: str) -> tuple[str, str | None]:
    raw_path = root / rel
    try:
        resolved = resolve_within_root(root, rel)
    except (PathOutsideWorkspace, OSError):
        return "rejected", None

    try:
        if raw_path.is_symlink():
            return "symlink", _sha256_bytes(os.readlink(raw_path).encode("utf-8", errors="surrogateescape"))
        if not resolved.is_file():
            return "other", None
        digest = hashlib.sha256()
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return "file", digest.hexdigest()
    except OSError:
        return "unreadable", None


def _git_worktree_state(root: Path) -> tuple[bool | None, str | None]:
    """Return a content-sensitive digest for tracked and untracked worktree state."""

    status = _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status is None:
        return None, None
    if not status:
        return False, _sha256_bytes(b"")

    digest = hashlib.sha256()
    digest.update(b"status\x00")
    digest.update(status)

    diff = _git_bytes(root, "diff", "--no-ext-diff", "--binary", "HEAD", "--")
    if diff is not None:
        digest.update(b"\x00diff\x00")
        digest.update(diff)

    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked is not None:
        for raw in sorted(part for part in untracked.split(b"\x00") if part):
            rel = raw.decode("utf-8", errors="surrogateescape")
            state, content_digest = _hash_untracked_path(root, rel)
            digest.update(b"\x00untracked\x00")
            digest.update(raw)
            digest.update(b"\x00")
            digest.update(state.encode("ascii"))
            if content_digest:
                digest.update(b"\x00")
                digest.update(content_digest.encode("ascii"))

    return True, digest.hexdigest()


def workspace_fingerprint(root: Path, changed_files: list[str] | None = None) -> dict:
    """Return the existing single-root workspace fingerprint contract."""

    root = root.resolve()
    changed = _changed_file_state(root, changed_files)
    index_identity = _stable_index_identity(root)
    index_digest = _stable_json_digest(index_identity) if index_identity is not None else None

    identity_payload = {
        "schema": 2,
        "git_head": _git_head(root),
        "index_state_sha256": index_digest,
        "changed_files": changed,
    }
    return {
        "root": str(root),
        **identity_payload,
        "fingerprint": _stable_json_digest(identity_payload),
    }


def repository_fingerprint(
    root: Path,
    relative_path: str,
    remote: str | None = None,
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    """Fingerprint one repository without hashing its absolute checkout location."""

    root = Path(root).resolve()
    canonical_remote = remote or _git_remote_identity(root)
    dirty, worktree_digest = _git_worktree_state(root)
    index_identity = _stable_index_identity(root)
    index_digest = _stable_json_digest(index_identity) if index_identity is not None else None
    identity_payload = {
        "schema": 1,
        "repository_id": repository_id(relative_path, canonical_remote),
        "relative_path": relative_path,
        "remote_identity": canonical_remote,
        "git_head": _git_head(root),
        "git_ref": _git_ref(root),
        "git_dirty": dirty,
        "git_worktree_sha256": worktree_digest,
        "index_state_sha256": index_digest,
        "changed_files": _changed_file_state(root, changed_files),
    }
    return {
        "root": str(root),
        **identity_payload,
        "fingerprint": _stable_json_digest(identity_payload),
    }


def aggregate_workspace_fingerprint(
    root: Path,
    config: dict,
    changed_files_by_repo: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Fingerprint the active repository set with one path-independent identity."""

    workspace_root = Path(root).resolve()
    changed_map = changed_files_by_repo or {}
    registry_by_path: dict[Path, Any] = {}
    for spec in load_registry(workspace_root, config):
        try:
            repo_root = (
                workspace_root
                if spec.relative_path == "."
                else resolve_within_root(workspace_root, spec.relative_path)
            )
        except (PathOutsideWorkspace, OSError):
            continue
        registry_by_path[repo_root] = spec

    snapshots: list[dict[str, Any]] = []
    for repo_root in workspace_roots(workspace_root, config):
        spec = registry_by_path.get(repo_root)
        if repo_root == workspace_root:
            relative = "."
        else:
            try:
                relative = repo_root.relative_to(workspace_root).as_posix()
            except ValueError:
                external_remote = _git_remote_identity(repo_root)
                stable_name = external_remote or repo_root.name.lower()
                relative = f"legacy:{stable_name}"

        canonical_remote = spec.remote_identity if spec is not None else _git_remote_identity(repo_root)
        snapshots.append(
            repository_fingerprint(
                repo_root,
                relative,
                canonical_remote,
                changed_map.get(relative),
            )
        )

    snapshots.sort(
        key=lambda item: (
            str(item["relative_path"]).lower(),
            item["repository_id"],
            item["fingerprint"],
        )
    )
    stable_repositories = [
        {key: value for key, value in snapshot.items() if key != "root"}
        for snapshot in snapshots
    ]
    identity_payload = {
        "schema": 1,
        "repositories": stable_repositories,
    }
    return {
        "root": str(workspace_root),
        "schema": 1,
        "repository_count": len(snapshots),
        "repositories": snapshots,
        "fingerprint": _stable_json_digest(identity_payload),
    }
