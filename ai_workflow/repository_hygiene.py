from __future__ import annotations

import subprocess
from pathlib import Path

from .io_utils import atomic_write_text


LOCAL_EXCLUDE_BEGIN = "# >>> ai-workflow local state >>>"
LOCAL_EXCLUDE_END = "# <<< ai-workflow local state <<<"
LOCAL_EXCLUDE_PATTERNS = (
    "/ai-workspace/config/repositories.json",
    "/ai-workspace/generated/",
    "/ai-workspace/indexes/",
    "/ai-workspace/code-review-graph/",
    "/ai-workspace/memory/",
    "/.code-review-graph/",
    "/.ai/",
)


def _git_output(root: Path, *args: str, timeout: int = 3) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _common_exclude_path(root: Path) -> Path | None:
    root = Path(root).resolve()
    raw = _git_output(root, "rev-parse", "--git-common-dir")
    if raw is None:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = root / common
    try:
        common = common.resolve()
    except OSError:
        return None
    if not common.is_dir():
        return None
    return common / "info" / "exclude"


def _managed_block() -> str:
    return (
        LOCAL_EXCLUDE_BEGIN
        + "\n"
        + "\n".join(LOCAL_EXCLUDE_PATTERNS)
        + "\n"
        + LOCAL_EXCLUDE_END
        + "\n"
    )


def _replace_managed_block(existing: str) -> tuple[str, str | None]:
    begin_count = existing.count(LOCAL_EXCLUDE_BEGIN)
    end_count = existing.count(LOCAL_EXCLUDE_END)
    if begin_count != end_count or begin_count > 1:
        return existing, "malformed_managed_block"

    block = _managed_block()
    if begin_count == 0:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return prefix + block, None

    start = existing.index(LOCAL_EXCLUDE_BEGIN)
    end = existing.index(LOCAL_EXCLUDE_END, start) + len(LOCAL_EXCLUDE_END)
    if end < len(existing) and existing[end] == "\n":
        end += 1
    return existing[:start] + block + existing[end:], None


def local_exclude_health(root: Path) -> dict:
    """Describe whether Git-local AI Workflow state exclusions are installed."""

    path = _common_exclude_path(Path(root))
    if path is None:
        return {
            "applicable": False,
            "installed": False,
            "changed": False,
            "path": None,
            "patterns": list(LOCAL_EXCLUDE_PATTERNS),
            "reason": "not_git_repository",
        }

    try:
        content = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        return {
            "applicable": True,
            "installed": False,
            "changed": False,
            "path": str(path),
            "patterns": list(LOCAL_EXCLUDE_PATTERNS),
            "reason": "exclude_unreadable",
            "error": str(exc),
        }

    begin_count = content.count(LOCAL_EXCLUDE_BEGIN)
    end_count = content.count(LOCAL_EXCLUDE_END)
    installed = (
        begin_count == 1
        and end_count == 1
        and all(pattern in content for pattern in LOCAL_EXCLUDE_PATTERNS)
    )
    return {
        "applicable": True,
        "installed": installed,
        "changed": False,
        "path": str(path),
        "patterns": list(LOCAL_EXCLUDE_PATTERNS),
        "reason": None if installed else "managed_block_missing",
    }


def install_local_excludes(root: Path) -> dict:
    """Install an idempotent Git-local ignore block for machine-only state."""

    path = _common_exclude_path(Path(root))
    if path is None:
        return {
            "applicable": False,
            "installed": False,
            "changed": False,
            "path": None,
            "patterns": list(LOCAL_EXCLUDE_PATTERNS),
            "reason": "not_git_repository",
        }

    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        return {
            "applicable": True,
            "installed": False,
            "changed": False,
            "path": str(path),
            "patterns": list(LOCAL_EXCLUDE_PATTERNS),
            "reason": "exclude_unreadable",
            "error": str(exc),
        }

    updated, error = _replace_managed_block(existing)
    if error is not None:
        return {
            "applicable": True,
            "installed": False,
            "changed": False,
            "path": str(path),
            "patterns": list(LOCAL_EXCLUDE_PATTERNS),
            "reason": error,
        }

    changed = updated != existing
    if changed:
        try:
            atomic_write_text(path, updated)
        except OSError as exc:
            return {
                "applicable": True,
                "installed": False,
                "changed": False,
                "path": str(path),
                "patterns": list(LOCAL_EXCLUDE_PATTERNS),
                "reason": "exclude_write_failed",
                "error": str(exc),
            }

    health = local_exclude_health(root)
    return {
        **health,
        "changed": changed,
    }


LOCAL_STATE_PROBES = (
    "ai-workspace/config/repositories.json",
    "ai-workspace/generated/index-state.json",
    "ai-workspace/indexes/repository/index-state.json",
    "ai-workspace/code-review-graph/repository/graph.db",
    "ai-workspace/memory/decisions.jsonl",
)


def _git_path_list(root: Path, *args: str, timeout: int = 5) -> list[str] | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [
        value
        for value in proc.stdout.split("\0")
        if value
    ]


def _is_explicitly_forbidden_tracked(path: str) -> bool:
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return False
    parts = normalized.split("/")
    name = parts[-1]

    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name.endswith(".pem") or name.endswith(".key"):
        return True
    if name.endswith(".log"):
        return True
    if "credentials" in parts or "secrets" in parts:
        return True

    if parts[0] in {".code-review-graph", ".ai"}:
        return True

    if parts[0] != "ai-workspace":
        return False

    if normalized == "ai-workspace/config/repositories.json":
        return True
    if normalized.startswith("ai-workspace/code-review-graph/"):
        return True
    if normalized.startswith("ai-workspace/indexes/"):
        return True
    if normalized.startswith("ai-workspace/generated/"):
        return normalized != "ai-workspace/generated/.gitkeep"
    if normalized.startswith("ai-workspace/memory/"):
        return normalized != "ai-workspace/memory/README.md"
    return False


def _path_is_ignored(root: Path, relative: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "git",
                "check-ignore",
                "--no-index",
                "-q",
                relative,
            ],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def repository_hygiene(root: Path) -> dict:
    """Inspect tracked Git state for generated or machine-local pollution."""

    root = Path(root).resolve()
    tracked = _git_path_list(root, "ls-files", "-z")
    if tracked is None:
        return {
            "applicable": False,
            "clean": True,
            "local_state_ignored": False,
            "tracked_files": 0,
            "tracked_forbidden": [],
            "ignored_tracked": [],
            "reason": "not_git_repository",
        }

    ignored_tracked = _git_path_list(
        root,
        "ls-files",
        "-ci",
        "--exclude-standard",
        "-z",
    )
    if ignored_tracked is None:
        ignored_tracked = []

    tracked_forbidden = sorted(
        path
        for path in tracked
        if _is_explicitly_forbidden_tracked(path)
    )
    ignored_tracked = sorted(set(ignored_tracked))
    local_state_ignored = all(
        _path_is_ignored(root, relative)
        for relative in LOCAL_STATE_PROBES
    )
    return {
        "applicable": True,
        "clean": not tracked_forbidden and not ignored_tracked,
        "local_state_ignored": local_state_ignored,
        "tracked_files": len(tracked),
        "tracked_forbidden": tracked_forbidden,
        "ignored_tracked": ignored_tracked,
        "reason": None,
    }
