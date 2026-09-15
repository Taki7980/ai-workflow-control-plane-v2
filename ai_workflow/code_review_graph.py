from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json
from .path_policy import PathOutsideWorkspace, resolve_within_root
from .repository_registry import RepositorySpec, is_git_repository, load_registry
from .workspace_state import repository_fingerprint


CRG_WORKSPACE_RELATIVE = Path("ai-workspace/code-review-graph")
CRG_MIN_SCHEMA_VERSION = 9
GRAPH_MANIFEST_SCHEMA = 1
_REQUIRED_GRAPH_TABLES = frozenset({"nodes", "edges", "metadata"})


class GraphValidationError(RuntimeError):
    """Raised when a Code Review Graph database cannot be trusted."""


def find_workspace_root(start: Path) -> Path:
    """Find the control-plane root for a repository or workspace path."""
    current = Path(start).expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "ai-workspace/config/control-plane.json").is_file():
            return candidate
    return current


def _repo_key(relative_path: str) -> str:
    value = relative_path.strip().replace("\\", "/")
    if value in {"", "."}:
        return "root"
    parts = []
    for raw in value.split("/"):
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-_")
        parts.append(cleaned or "repo")
    return "__".join(parts)


def _repository_relative_path(
    workspace_root: Path,
    repository_root: Path,
) -> str:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    try:
        return repository.relative_to(workspace).as_posix() or "."
    except ValueError:
        # Legacy explicit external roots remain isolated by their directory name.
        return f"external/{repository.name}"


def repository_data_dir(workspace_root: Path, repository_root: Path) -> Path:
    workspace = Path(workspace_root).resolve()
    relative = _repository_relative_path(workspace, repository_root)
    return resolve_within_root(
        workspace,
        CRG_WORKSPACE_RELATIVE / _repo_key(relative),
    )


def _resolve_spec_root(workspace_root: Path, spec: RepositorySpec) -> Path | None:
    try:
        if spec.relative_path == ".":
            candidate = Path(workspace_root).resolve()
        else:
            candidate = resolve_within_root(workspace_root, spec.relative_path)
    except (PathOutsideWorkspace, OSError):
        return None
    if not candidate.is_dir() or not is_git_repository(candidate):
        return None
    return candidate


def managed_repositories(
    workspace_root: Path,
    config: dict | None = None,
) -> list[dict[str, Any]]:
    """Return active Git repositories backed by the workspace registry."""
    root = Path(workspace_root).resolve()
    rows: list[dict[str, Any]] = []
    for spec in load_registry(root, config):
        if not spec.included:
            continue
        repository_root = _resolve_spec_root(root, spec)
        if repository_root is None:
            continue
        rows.append(
            {
                "relative_path": spec.relative_path,
                "repository_root": repository_root,
                "data_dir": repository_data_dir(root, repository_root),
            }
        )

    # Keep a root Git repository usable before/without a registry.
    if not rows and is_git_repository(root):
        rows.append(
            {
                "relative_path": ".",
                "repository_root": root,
                "data_dir": repository_data_dir(root, root),
            }
        )
    return rows


def crg_environment(workspace_root: Path, repository_root: Path) -> dict[str, str]:
    data_dir = repository_data_dir(workspace_root, repository_root)
    env = dict(os.environ)
    env["CRG_DATA_DIR"] = str(data_dir)
    env["CRG_REPO_ROOT"] = str(Path(repository_root).resolve())
    return env


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_graph_database(
    graph_path: Path,
    *,
    minimum_schema_version: int = CRG_MIN_SCHEMA_VERSION,
) -> dict[str, int]:
    """Validate the stable SQLite contract needed by the control plane."""

    path = Path(graph_path)
    if not path.is_file():
        raise GraphValidationError("graph.db is missing")

    try:
        resolved = path.resolve(strict=True)
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    except (OSError, sqlite3.DatabaseError) as exc:
        raise GraphValidationError(f"cannot open graph.db read-only: {exc}") from exc

    try:
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchall()
            if quick_check != [("ok",)]:
                raise GraphValidationError(
                    f"SQLite quick_check failed: {quick_check[:3]}"
                )

            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = sorted(_REQUIRED_GRAPH_TABLES - tables)
            if missing:
                raise GraphValidationError(
                    f"missing required graph tables: {', '.join(missing)}"
                )

            metadata = {
                str(key): str(value)
                for key, value in connection.execute(
                    "SELECT key, value FROM metadata"
                )
            }
            raw_schema = metadata.get("schema_version")
            try:
                schema_version = int(raw_schema) if raw_schema is not None else 0
            except ValueError as exc:
                raise GraphValidationError(
                    f"invalid schema_version metadata: {raw_schema!r}"
                ) from exc
            if schema_version < minimum_schema_version:
                raise GraphValidationError(
                    "unsupported CRG schema "
                    f"{schema_version}; need >= {minimum_schema_version}"
                )

            node_count = int(
                connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            )
            edge_count = int(
                connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            )
            if node_count <= 0:
                raise GraphValidationError("graph contains zero nodes")
        except sqlite3.DatabaseError as exc:
            raise GraphValidationError(f"invalid graph database: {exc}") from exc

        return {
            "schema_version": schema_version,
            "node_count": node_count,
            "edge_count": edge_count,
        }
    finally:
        connection.close()


def graph_exists(workspace_root: Path, repository_root: Path) -> bool:
    return (repository_data_dir(workspace_root, repository_root) / "graph.db").is_file()


def graph_freshness(
    workspace_root: Path,
    repository_root: Path,
) -> dict[str, Any]:
    """Verify graph bytes and provenance match the current repository state."""

    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    data_dir = repository_data_dir(workspace, repository)
    graph = data_dir / "graph.db"
    manifest_path = data_dir / "manifest.json"
    result: dict[str, Any] = {
        "fresh": False,
        "data_dir": str(data_dir),
        "graph": str(graph),
        "manifest": str(manifest_path),
        "reason": "",
    }

    if not graph.is_file():
        result["reason"] = "graph.db is missing"
        return result
    if not manifest_path.is_file():
        result["reason"] = "manifest.json is missing"
        return result

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        result["reason"] = "manifest.json is unreadable"
        return result
    if not isinstance(manifest, dict):
        result["reason"] = "manifest.json must contain an object"
        return result
    if int(manifest.get("manifest_schema", 0) or 0) != GRAPH_MANIFEST_SCHEMA:
        result["reason"] = "unsupported manifest schema"
        return result

    relative = _repository_relative_path(workspace, repository)
    if manifest.get("repository_relative_path") != relative:
        result["reason"] = "repository path identity mismatch"
        return result

    try:
        graph_sha256 = _sha256_file(graph)
    except OSError:
        result["reason"] = "graph.db is unreadable"
        return result
    if manifest.get("graph_sha256") != graph_sha256:
        result["reason"] = "graph hash mismatch"
        return result

    current = repository_fingerprint(repository, relative)
    if manifest.get("repository_fingerprint") != current.get("fingerprint"):
        result["reason"] = "repository fingerprint mismatch"
        result["manifest_fingerprint"] = manifest.get(
            "repository_fingerprint"
        )
        result["current_fingerprint"] = current.get("fingerprint")
        return result
    if manifest.get("git_head") != current.get("git_head"):
        result["reason"] = "Git HEAD mismatch"
        return result

    result.update(
        {
            "fresh": True,
            "reason": "graph provenance matches repository state",
            "graph_sha256": graph_sha256,
            "repository_fingerprint": current.get("fingerprint"),
            "git_head": current.get("git_head"),
        }
    )
    return result


def any_graph_ready(workspace_root: Path, config: dict | None = None) -> bool:
    if shutil.which("code-review-graph") is None:
        return False
    try:
        rows = managed_repositories(workspace_root, config)
    except (PathOutsideWorkspace, OSError):
        return False
    for row in rows:
        try:
            validate_graph_database(row["data_dir"] / "graph.db")
            freshness = graph_freshness(
                workspace_root,
                row["repository_root"],
            )
        except (GraphValidationError, OSError):
            continue
        if not freshness.get("fresh"):
            continue
        return True
    return False


def _run(
    workspace_root: Path,
    repository_root: Path,
    args: list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    data_dir = repository_data_dir(workspace_root, repository_root)
    data_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["code-review-graph", *args],
        cwd=repository_root,
        env=crg_environment(workspace_root, repository_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _crg_version(executable: str, *, timeout: int = 5) -> str:
    try:
        proc = subprocess.run(
            [executable, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    value = (proc.stdout or proc.stderr).strip().splitlines()
    return value[0][:200] if value else "unknown"


def _write_graph_manifest(
    *,
    repository_root: Path,
    relative_path: str,
    data_dir: Path,
    action: str,
    crg_version: str,
    validation: dict[str, int],
) -> dict[str, Any]:
    graph = data_dir / "graph.db"
    fingerprint = repository_fingerprint(repository_root, relative_path)
    manifest: dict[str, Any] = {
        "manifest_schema": GRAPH_MANIFEST_SCHEMA,
        "repository_relative_path": relative_path,
        "repository_fingerprint": fingerprint["fingerprint"],
        "git_head": fingerprint.get("git_head"),
        "crg_version": crg_version,
        "crg_schema_version": validation["schema_version"],
        "generation_mode": action,
        "graph_file": "graph.db",
        "graph_sha256": _sha256_file(graph),
        "node_count": validation["node_count"],
        "edge_count": validation["edge_count"],
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    atomic_write_json(
        data_dir / "manifest.json",
        manifest,
        sort_keys=True,
    )
    return manifest


def repository_health(
    workspace_root: Path,
    repository_root: Path,
    *,
    timeout: int = 8,
) -> dict[str, Any]:
    repo = Path(repository_root).resolve()
    try:
        data_dir = repository_data_dir(workspace_root, repo)
    except (PathOutsideWorkspace, OSError) as exc:
        return {
            "repository_root": str(repo),
            "data_dir": None,
            "ready": False,
            "error": f"unsafe central graph path: {exc}",
        }

    result: dict[str, Any] = {
        "repository_root": str(repo),
        "data_dir": str(data_dir),
        "ready": False,
    }
    if shutil.which("code-review-graph") is None:
        result["error"] = "code-review-graph is not installed"
        return result

    graph = data_dir / "graph.db"
    if not graph.is_file():
        result["error"] = "central graph is not built"
        return result

    try:
        result["validation"] = validate_graph_database(graph)
    except GraphValidationError as exc:
        result["error"] = f"graph validation failed: {exc}"
        return result

    result["freshness"] = graph_freshness(workspace_root, repo)
    if not result["freshness"].get("fresh"):
        result["error"] = (
            "graph provenance stale: "
            + str(result["freshness"].get("reason") or "unknown reason")
        )
        return result

    try:
        proc = _run(
            workspace_root,
            repo,
            ["status", "--repo", str(repo), "--json"],
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, PathOutsideWorkspace) as exc:
        result["error"] = str(exc)
        return result
    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout).strip()[:500]
        return result

    result["ready"] = True
    if proc.stdout.strip():
        try:
            result["status"] = json.loads(proc.stdout)
        except json.JSONDecodeError:
            result["status"] = proc.stdout.strip()[:1000]
    return result


def workspace_health(
    workspace_root: Path,
    config: dict | None = None,
    *,
    timeout: int = 8,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    installed = shutil.which("code-review-graph") is not None
    repositories = []
    try:
        rows = managed_repositories(root, config)
    except (PathOutsideWorkspace, OSError) as exc:
        return {
            "installed": installed,
            "ready": False,
            "data_root": str(root / CRG_WORKSPACE_RELATIVE),
            "repository_count": 0,
            "ready_repositories": 0,
            "repositories": [],
            "error": f"unsafe central graph path: {exc}",
        }

    for row in rows:
        health = repository_health(root, row["repository_root"], timeout=timeout)
        health["relative_path"] = row["relative_path"]
        repositories.append(health)
    ready_count = sum(1 for row in repositories if row.get("ready"))
    return {
        "installed": installed,
        "ready": bool(repositories) and ready_count == len(repositories),
        "data_root": str(root / CRG_WORKSPACE_RELATIVE),
        "repository_count": len(repositories),
        "ready_repositories": ready_count,
        "repositories": repositories,
    }


def sync_workspace_graphs(
    workspace_root: Path,
    config: dict | None = None,
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    """Build missing graphs and incrementally refresh existing central graphs."""
    root = Path(workspace_root).resolve()
    executable = shutil.which("code-review-graph")

    try:
        rows = managed_repositories(root, config)
    except (PathOutsideWorkspace, OSError) as exc:
        return {
            "installed": executable is not None,
            "attempted": 0,
            "ready": 0,
            "data_root": str(root / CRG_WORKSPACE_RELATIVE),
            "repositories": [],
            "error": f"unsafe central graph path: {exc}",
        }

    if executable is None:
        return {
            "installed": False,
            "attempted": 0,
            "ready": 0,
            "data_root": str(root / CRG_WORKSPACE_RELATIVE),
            "repositories": [],
        }

    crg_version = _crg_version(executable)
    results: list[dict[str, Any]] = []
    for row in rows:
        repo = row["repository_root"]
        data_dir = row["data_dir"]
        graph = data_dir / "graph.db"
        action = "update" if graph.is_file() else "build"
        entry: dict[str, Any] = {
            "relative_path": row["relative_path"],
            "repository_root": str(repo),
            "data_dir": str(data_dir),
            "action": action,
            "ok": False,
        }

        try:
            proc = _run(
                root,
                repo,
                [action, "--repo", str(repo), "--quiet"],
                timeout=timeout,
            )
            if proc.returncode != 0:
                entry["error"] = (proc.stderr or proc.stdout).strip()[:500]
            elif not graph.is_file():
                entry["error"] = "graph database was not created"
            else:
                try:
                    validation = validate_graph_database(graph)
                except GraphValidationError as exc:
                    entry["error"] = f"graph validation failed: {exc}"
                else:
                    manifest = _write_graph_manifest(
                        repository_root=repo,
                        relative_path=row["relative_path"],
                        data_dir=data_dir,
                        action=action,
                        crg_version=crg_version,
                        validation=validation,
                    )
                    entry["validation"] = validation
                    entry["manifest"] = str(data_dir / "manifest.json")
                    entry["graph_sha256"] = manifest["graph_sha256"]
                    entry["ok"] = True
        except (
            OSError,
            subprocess.TimeoutExpired,
            PathOutsideWorkspace,
        ) as exc:
            entry["error"] = str(exc)
        results.append(entry)

    return {
        "installed": True,
        "attempted": len(results),
        "ready": sum(1 for row in results if row.get("ok")),
        "data_root": str(root / CRG_WORKSPACE_RELATIVE),
        "repositories": results,
    }
