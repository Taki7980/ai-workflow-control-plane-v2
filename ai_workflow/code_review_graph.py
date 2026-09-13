from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .path_policy import PathOutsideWorkspace, resolve_within_root
from .repository_registry import RepositorySpec, is_git_repository, load_registry


CRG_WORKSPACE_RELATIVE = Path("ai-workspace/code-review-graph")


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


def repository_data_dir(workspace_root: Path, repository_root: Path) -> Path:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    try:
        relative = repository.relative_to(workspace).as_posix() or "."
    except ValueError:
        # Legacy explicit external roots remain isolated by their directory name.
        relative = f"external/{repository.name}"
    return workspace / CRG_WORKSPACE_RELATIVE / _repo_key(relative)


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


def managed_repositories(workspace_root: Path, config: dict | None = None) -> list[dict[str, Any]]:
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


def graph_exists(workspace_root: Path, repository_root: Path) -> bool:
    return (repository_data_dir(workspace_root, repository_root) / "graph.db").is_file()


def any_graph_ready(workspace_root: Path, config: dict | None = None) -> bool:
    if shutil.which("code-review-graph") is None:
        return False
    return any(
        (row["data_dir"] / "graph.db").is_file()
        for row in managed_repositories(workspace_root, config)
    )


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


def repository_health(
    workspace_root: Path,
    repository_root: Path,
    *,
    timeout: int = 8,
) -> dict[str, Any]:
    repo = Path(repository_root).resolve()
    data_dir = repository_data_dir(workspace_root, repo)
    result: dict[str, Any] = {
        "repository_root": str(repo),
        "data_dir": str(data_dir),
        "ready": False,
    }
    if shutil.which("code-review-graph") is None:
        result["error"] = "code-review-graph is not installed"
        return result
    if not (data_dir / "graph.db").is_file():
        result["error"] = "central graph is not built"
        return result
    try:
        proc = _run(
            workspace_root,
            repo,
            ["status", "--repo", str(repo), "--json"],
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
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
    for row in managed_repositories(root, config):
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
    rows = managed_repositories(root, config)
    if executable is None:
        return {
            "installed": False,
            "attempted": 0,
            "ready": 0,
            "data_root": str(root / CRG_WORKSPACE_RELATIVE),
            "repositories": [],
        }

    results: list[dict[str, Any]] = []
    for row in rows:
        repo = row["repository_root"]
        data_dir = row["data_dir"]
        action = "update" if (data_dir / "graph.db").is_file() else "build"
        try:
            proc = _run(
                root,
                repo,
                [action, "--repo", str(repo), "--quiet"],
                timeout=timeout,
            )
            entry: dict[str, Any] = {
                "relative_path": row["relative_path"],
                "repository_root": str(repo),
                "data_dir": str(data_dir),
                "action": action,
                "ok": proc.returncode == 0 and (data_dir / "graph.db").is_file(),
            }
            if not entry["ok"]:
                entry["error"] = (proc.stderr or proc.stdout).strip()[:500]
        except (OSError, subprocess.TimeoutExpired) as exc:
            entry = {
                "relative_path": row["relative_path"],
                "repository_root": str(repo),
                "data_dir": str(data_dir),
                "action": action,
                "ok": False,
                "error": str(exc),
            }
        results.append(entry)

    return {
        "installed": True,
        "attempted": len(results),
        "ready": sum(1 for row in results if row.get("ok")),
        "data_root": str(root / CRG_WORKSPACE_RELATIVE),
        "repositories": results,
    }
