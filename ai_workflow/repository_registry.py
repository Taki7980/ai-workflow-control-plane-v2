from __future__ import annotations

import configparser
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_REGISTRY_VERSION = 1
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".ai",
    "ai-workspace",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
}


@dataclass(frozen=True)
class RepositorySpec:
    """A local Git repository discovered inside an AI Workflow workspace.

    The spec is intentionally explicit and not enabled by default. Users must
    accept discovered repositories before the control plane uses them for
    retrieval or write-capable workflows.
    """

    name: str
    relative_path: str
    git_dir: str | None = None
    remote_url: str | None = None
    remote_identity: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    included: bool = False
    reason: str = "discovered"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.name
    value = rel.as_posix()
    return "." if value == "" else value


def _git_dir(repo: Path) -> Path | None:
    dotgit = repo / ".git"
    if dotgit.is_dir():
        return dotgit.resolve()
    if dotgit.is_file():
        try:
            text = dotgit.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        prefix = "gitdir:"
        if not text.lower().startswith(prefix):
            return None
        raw = text[len(prefix):].strip()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = dotgit.parent / candidate
        try:
            return candidate.resolve()
        except OSError:
            return None
    return None


def _read_ref(git_dir: Path, ref: str) -> str | None:
    ref_path = git_dir / ref
    try:
        if ref_path.is_file():
            value = ref_path.read_text(encoding="utf-8", errors="replace").strip()
            return value or None
    except OSError:
        return None

    packed = git_dir / "packed-refs"
    try:
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0].strip()
    except OSError:
        return None
    return None


def _read_head(git_dir: Path) -> tuple[str | None, str | None]:
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None, None
    if head.lower().startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        return ref, _read_ref(git_dir, ref)
    return None, head or None


def _read_remote(git_dir: Path) -> str | None:
    config_path = git_dir / "config"
    parser = configparser.ConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeError):
        return None
    section = 'remote "origin"'
    if parser.has_section(section):
        value = parser.get(section, "url", fallback="").strip()
        return value or None
    for name in parser.sections():
        if name.startswith("remote "):
            value = parser.get(name, "url", fallback="").strip()
            if value:
                return value
    return None


def remote_identity(remote_url: str | None) -> str | None:
    """Return a credential-free stable remote identity."""

    if not remote_url:
        return None
    raw = remote_url.strip()
    if not raw:
        return None

    if "@" in raw and ":" in raw and "://" not in raw:
        host_part, path_part = raw.split(":", 1)
        host = host_part.rsplit("@", 1)[-1].lower()
        path = path_part.strip("/")
    else:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or parsed.netloc.rsplit("@", 1)[-1]
            path = parsed.path.strip("/")
        else:
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
            return f"opaque:{digest}"
    if path.endswith(".git"):
        path = path[:-4]
    if not host or not path:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"opaque:{digest}"
    return f"{host.lower()}/{path.lower()}"


def discover_repositories(
    root: Path,
    *,
    max_depth: int = 3,
    include_nested: bool = False,
    skip_dirs: set[str] | None = None,
) -> list[RepositorySpec]:
    """Discover local Git repositories under a parent workspace.

    Discovery is deterministic, pure-Python, and read-only. It avoids invoking
    Git so first-run setup works even before a user's shell/Git credentials are
    fully configured.
    """

    base = Path(root).expanduser().resolve()
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if not base.is_dir():
        return []
    ignored = set(_SKIP_DIRS)
    if skip_dirs:
        ignored.update(skip_dirs)

    found: list[RepositorySpec] = []

    def walk(directory: Path, depth: int) -> None:
        git_dir = _git_dir(directory)
        if git_dir is not None:
            remote = _read_remote(git_dir)
            head_ref, head_sha = _read_head(git_dir)
            rel = _safe_relative(directory, base)
            found.append(
                RepositorySpec(
                    name=directory.name,
                    relative_path=rel,
                    git_dir=_safe_relative(git_dir, base),
                    remote_url=remote,
                    remote_identity=remote_identity(remote),
                    head_ref=head_ref,
                    head_sha=head_sha,
                )
            )
            if not include_nested:
                return
        if depth >= max_depth:
            return
        try:
            children = sorted(
                (child for child in directory.iterdir() if child.is_dir()),
                key=lambda path: path.name.lower(),
            )
        except OSError:
            return
        for child in children:
            if child.name in ignored:
                continue
            walk(child, depth + 1)

    walk(base, 0)
    return found


def registry_payload(repositories: list[RepositorySpec]) -> dict[str, Any]:
    """Build the persisted review-required repository registry payload."""

    return {
        "version": _REGISTRY_VERSION,
        "review_required": True,
        "repositories": [
            asdict(repo)
            for repo in sorted(
                repositories,
                key=lambda repo: (repo.relative_path.lower(), repo.remote_identity or "", repo.name.lower()),
            )
        ],
    }


def workspace_registry_fingerprint(repositories: list[RepositorySpec]) -> str:
    """Hash the accepted repo identity set without leaking absolute paths."""

    accepted = [
        {
            "relative_path": repo.relative_path,
            "remote_identity": repo.remote_identity,
            "head_ref": repo.head_ref,
            "head_sha": repo.head_sha,
            "included": bool(repo.included),
        }
        for repo in sorted(repositories, key=lambda repo: repo.relative_path.lower())
    ]
    payload = json.dumps(accepted, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
