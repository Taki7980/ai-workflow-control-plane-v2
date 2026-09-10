from __future__ import annotations

import configparser
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .io_utils import atomic_write_json


_REGISTRY_VERSION = 1
_DEFAULT_REGISTRY = Path("ai-workspace/config/repositories.json")
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
    """A local Git repository discovered inside an AI Workflow workspace."""

    name: str
    relative_path: str
    git_dir: str | None = None
    remote_identity: str | None = None
    head_ref: str | None = None
    head_sha: str | None = None
    included: bool = False
    reason: str = "discovered"


def repository_id(relative_path: str, remote_identity: str | None) -> str:
    payload = json.dumps(
        {"relative_path": relative_path, "remote_identity": remote_identity},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def registry_path(root: Path, config: dict | None = None) -> Path:
    workspace = ((config or {}).get("workspace") or {})
    configured = workspace.get("registry") or _DEFAULT_REGISTRY.as_posix()
    path = Path(str(configured))
    return path if path.is_absolute() else Path(root).resolve() / path


def _relative_or_none(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
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
            resolved = candidate.resolve()
        except OSError:
            return None
        return resolved if resolved.is_dir() else None
    return None


def _common_git_dir(git_dir: Path) -> Path:
    """Return the shared Git directory for a normal repo or linked worktree."""

    commondir = git_dir / "commondir"
    try:
        raw = commondir.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return git_dir
    if not raw:
        return git_dir
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = git_dir / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return git_dir
    return resolved if resolved.is_dir() else git_dir


def is_git_repository(path: Path) -> bool:
    return _git_dir(Path(path)) is not None


def _read_ref_from_dir(base: Path, ref: str) -> str | None:
    ref_path = base / ref
    try:
        if ref_path.is_file():
            value = ref_path.read_text(encoding="utf-8", errors="replace").strip()
            return value or None
    except OSError:
        return None

    packed = base / "packed-refs"
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


def _read_ref(git_dir: Path, ref: str) -> str | None:
    common = _common_git_dir(git_dir)
    for base in (git_dir, common):
        value = _read_ref_from_dir(base, ref)
        if value:
            return value
        if base == common:
            break
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
    config_path = _common_git_dir(git_dir) / "config"
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


def _spec_for_directory(
    directory: Path,
    base: Path,
    *,
    included: bool = False,
    reason: str = "discovered",
) -> RepositorySpec | None:
    git_dir = _git_dir(directory)
    if git_dir is None:
        return None
    rel = _relative_or_none(directory, base)
    if rel is None:
        return None
    raw_remote = _read_remote(git_dir)
    head_ref, head_sha = _read_head(git_dir)
    return RepositorySpec(
        name=directory.name,
        relative_path=rel,
        git_dir=_relative_or_none(git_dir, base),
        remote_identity=remote_identity(raw_remote),
        head_ref=head_ref,
        head_sha=head_sha,
        included=included,
        reason=reason,
    )


def discover_repositories(
    root: Path,
    *,
    max_depth: int = 3,
    include_nested: bool = False,
    skip_dirs: set[str] | None = None,
) -> list[RepositorySpec]:
    """Discover local Git repositories under a parent workspace, read-only."""

    base = Path(root).expanduser().resolve()
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")
    if not base.is_dir():
        return []
    ignored = set(_SKIP_DIRS)
    if skip_dirs:
        ignored.update(skip_dirs)

    found: list[RepositorySpec] = []
    visited: set[Path] = set()

    def walk(directory: Path, depth: int) -> None:
        try:
            resolved_directory = directory.resolve()
            resolved_directory.relative_to(base)
        except (OSError, ValueError):
            return
        if resolved_directory in visited:
            return
        visited.add(resolved_directory)

        spec = _spec_for_directory(resolved_directory, base)
        if spec is not None:
            found.append(spec)
            if not include_nested:
                return
        if depth >= max_depth:
            return
        try:
            children = sorted(
                (child for child in resolved_directory.iterdir() if child.is_dir()),
                key=lambda path: path.name.lower(),
            )
        except OSError:
            return
        for child in children:
            if child.name in ignored:
                continue
            walk(child, depth + 1)

    walk(base, 0)
    return sorted(
        found,
        key=lambda repo: (
            repo.relative_path.lower(),
            repo.remote_identity or "",
            repo.name.lower(),
        ),
    )


def _entry(repo: RepositorySpec) -> dict[str, Any]:
    return {
        "repository_id": repository_id(repo.relative_path, repo.remote_identity),
        "name": repo.name,
        "relative_path": repo.relative_path,
        "git_dir": repo.git_dir,
        "remote_identity": repo.remote_identity,
        "head_ref": repo.head_ref,
        "head_sha": repo.head_sha,
        "included": bool(repo.included),
        "reason": repo.reason,
    }


def registry_payload(repositories: list[RepositorySpec]) -> dict[str, Any]:
    """Build the persisted review-required, credential-free registry payload."""

    ordered = sorted(
        repositories,
        key=lambda repo: (
            repo.relative_path.lower(),
            repo.remote_identity or "",
            repo.name.lower(),
        ),
    )
    return {
        "version": _REGISTRY_VERSION,
        "review_required": True,
        "repositories": [_entry(repo) for repo in ordered],
    }


def _entry_to_spec(entry: object) -> RepositorySpec | None:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    relative_path = entry.get("relative_path")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    remote = entry.get("remote_identity")
    git_dir = entry.get("git_dir")
    head_ref = entry.get("head_ref")
    head_sha = entry.get("head_sha")
    reason = entry.get("reason", "discovered")
    included = entry.get("included", False)
    if remote is not None and not isinstance(remote, str):
        return None
    if git_dir is not None and not isinstance(git_dir, str):
        return None
    if head_ref is not None and not isinstance(head_ref, str):
        return None
    if head_sha is not None and not isinstance(head_sha, str):
        return None
    if not isinstance(reason, str) or not isinstance(included, bool):
        return None
    spec = RepositorySpec(
        name=name.strip(),
        relative_path=relative_path.strip(),
        git_dir=git_dir,
        remote_identity=remote,
        head_ref=head_ref,
        head_sha=head_sha,
        included=included,
        reason=reason,
    )
    persisted_id = entry.get("repository_id")
    if persisted_id is not None:
        if not isinstance(persisted_id, str):
            return None
        if persisted_id != repository_id(spec.relative_path, spec.remote_identity):
            return None
    return spec


def load_registry(root: Path, config: dict | None = None) -> list[RepositorySpec]:
    """Load a valid registry. Any malformed or ambiguous state fails closed."""

    path = registry_path(root, config)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict) or data.get("version") != _REGISTRY_VERSION:
        return []
    repositories = data.get("repositories")
    if not isinstance(repositories, list):
        return []

    specs: list[RepositorySpec] = []
    seen: set[tuple[str, str | None]] = set()
    for raw in repositories:
        spec = _entry_to_spec(raw)
        if spec is None:
            return []
        key = (spec.relative_path, spec.remote_identity)
        if key in seen:
            return []
        seen.add(key)
        specs.append(spec)
    return sorted(
        specs,
        key=lambda repo: (
            repo.relative_path.lower(),
            repo.remote_identity or "",
            repo.name.lower(),
        ),
    )


def workspace_registry_fingerprint(repositories: list[RepositorySpec]) -> str:
    """Hash the repository identity set without leaking absolute paths."""

    payload = [
        {
            "repository_id": repository_id(repo.relative_path, repo.remote_identity),
            "relative_path": repo.relative_path,
            "remote_identity": repo.remote_identity,
            "head_ref": repo.head_ref,
            "head_sha": repo.head_sha,
            "included": bool(repo.included),
        }
        for repo in sorted(
            repositories,
            key=lambda repo: (repo.relative_path.lower(), repo.remote_identity or ""),
        )
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def registry_summary(root: Path, config: dict | None = None) -> dict[str, Any]:
    repositories = load_registry(root, config)
    return {
        "path": str(registry_path(root, config)),
        "version": _REGISTRY_VERSION,
        "review_required": True,
        "discovered": len(repositories),
        "accepted": sum(1 for repo in repositories if repo.included),
        "fingerprint": workspace_registry_fingerprint(repositories),
        "repositories": [_entry(repo) for repo in repositories],
    }


def refresh_registry(
    root: Path,
    *,
    max_depth: int = 3,
    config: dict | None = None,
) -> dict[str, Any]:
    """Rediscover repositories while preserving only unchanged explicit decisions."""

    existing = {
        (repo.relative_path, repo.remote_identity): repo
        for repo in load_registry(root, config)
    }
    discovered = discover_repositories(root, max_depth=max_depth)
    merged: list[RepositorySpec] = []
    for repo in discovered:
        previous = existing.get((repo.relative_path, repo.remote_identity))
        merged.append(
            replace(
                repo,
                included=bool(previous.included) if previous is not None else False,
                reason=previous.reason if previous is not None else repo.reason,
            )
        )
    atomic_write_json(registry_path(root, config), registry_payload(merged))
    return registry_summary(root, config)


def _matches_selector(repo: RepositorySpec, selector: str) -> bool:
    return selector in {
        repo.relative_path,
        repository_id(repo.relative_path, repo.remote_identity),
        repo.remote_identity or "",
        repo.name,
    }


def set_repository_included(
    root: Path,
    selector: str,
    included: bool,
    config: dict | None = None,
) -> dict[str, Any]:
    """Set inclusion for exactly one repository selected by a stable identifier."""

    value = str(selector or "").strip()
    if not value:
        raise ValueError("repository selector must not be blank")
    repositories = load_registry(root, config)
    matches = [repo for repo in repositories if _matches_selector(repo, value)]
    if not matches:
        raise ValueError(f"repository not found: {value}")
    if len(matches) != 1:
        raise ValueError(f"repository selector is ambiguous: {value}")

    target = matches[0]
    updated = [
        replace(repo, included=bool(included)) if repo == target else repo
        for repo in repositories
    ]
    atomic_write_json(registry_path(root, config), registry_payload(updated))
    result = registry_summary(root, config)
    result["changed"] = {
        **_entry(replace(target, included=bool(included))),
        "action": "included" if included else "excluded",
    }
    return result
