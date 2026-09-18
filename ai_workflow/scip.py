from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .code_review_graph import find_workspace_root
from .io_utils import atomic_write_json
from .models import ContextItem
from .path_policy import PathOutsideWorkspace, resolve_within_root
from .workspace import active_repository_roots
from .workspace_state import repository_fingerprint


SCIP_WORKSPACE_RELATIVE = Path("ai-workspace/scip")
SCIP_MANIFEST_SCHEMA = 1
_SKIP_DIRS = {
    ".git",
    ".ai",
    "ai-workspace",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


@dataclass(frozen=True)
class ScipIndexer:
    language: str
    executable: str
    args: tuple[str, ...]


def _repository_relative_path(workspace_root: Path, repository_root: Path) -> str:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    try:
        return repository.relative_to(workspace).as_posix() or "."
    except ValueError:
        return f"external/{repository.name}"


def _repo_key(relative_path: str) -> str:
    value = relative_path.strip().replace("\\", "/")
    if value in {"", "."}:
        return "root"
    parts = [
        re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-_") or "repo"
        for raw in value.split("/")
    ]
    return "__".join(parts)


def scip_data_dir(workspace_root: Path, repository_root: Path) -> Path:
    workspace = Path(workspace_root).resolve()
    relative = _repository_relative_path(workspace, repository_root)
    return resolve_within_root(
        workspace,
        SCIP_WORKSPACE_RELATIVE / _repo_key(relative),
    )


def _has_source(root: Path, suffixes: set[str]) -> bool:
    for _current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS]
        if any(Path(name).suffix.lower() in suffixes for name in files):
            return True
    return False


def _indexer_for(root: Path, language: str) -> ScipIndexer | None:
    name = language.strip().lower().replace("javascript/typescript", "typescript")
    aliases = {"py": "python", "ts": "typescript", "js": "javascript", "golang": "go"}
    name = aliases.get(name, name)
    if name == "python":
        return ScipIndexer("python", "scip-python", ("index", ".", "--project-name", root.name))
    if name == "typescript":
        return ScipIndexer("typescript", "scip-typescript", ("index",))
    if name == "javascript":
        return ScipIndexer("javascript", "scip-typescript", ("index", "--infer-tsconfig"))
    if name == "java":
        return ScipIndexer("java", "scip-java", ("index",))
    if name == "go":
        return ScipIndexer("go", "scip-go", ("./...",))
    return None


def detect_indexer(root: Path, language: str | None = None) -> ScipIndexer | None:
    root = Path(root).resolve()
    if language:
        return _indexer_for(root, language)

    candidates: list[ScipIndexer] = []

    def add_candidate(language_name: str) -> None:
        candidate = _indexer_for(root, language_name)
        if candidate is not None:
            candidates.append(candidate)

    if (root / "go.mod").is_file() and _has_source(root, {".go"}):
        add_candidate("go")
    if any(
        (root / marker).exists()
        for marker in ("pom.xml", "build.gradle", "build.gradle.kts", "gradlew")
    ) and _has_source(root, {".java"}):
        add_candidate("java")
    if (root / "tsconfig.json").is_file() and _has_source(
        root,
        {".ts", ".tsx"},
    ):
        add_candidate("typescript")
    if any(
        (root / marker).is_file()
        for marker in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
    ) and _has_source(root, {".py"}):
        add_candidate("python")
    if (root / "package.json").is_file() and _has_source(
        root,
        {".js", ".jsx"},
    ):
        add_candidate("javascript")

    return candidates[0] if len(candidates) == 1 else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scip_status(workspace_root: Path, repository_root: Path) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    try:
        data_dir = scip_data_dir(workspace, repository)
    except (PathOutsideWorkspace, OSError) as exc:
        return {"ready": False, "reason": f"unsafe SCIP state path: {exc}"}

    index_path = data_dir / "index.scip"
    json_path = data_dir / "index.json"
    manifest_path = data_dir / "manifest.json"
    result: dict[str, Any] = {
        "ready": False,
        "data_dir": str(data_dir),
        "index": str(index_path),
        "json": str(json_path),
        "manifest": str(manifest_path),
    }
    if not index_path.is_file():
        result["reason"] = "index.scip is missing"
        return result
    if not manifest_path.is_file():
        result["reason"] = "manifest.json is missing"
        return result
    if not json_path.is_file():
        result["reason"] = "index.json is missing"
        return result

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        result["reason"] = "SCIP manifest or JSON is unreadable"
        return result
    if not isinstance(manifest, dict) or manifest.get("manifest_schema") != SCIP_MANIFEST_SCHEMA:
        result["reason"] = "unsupported SCIP manifest schema"
        return result
    if not isinstance(payload, dict):
        result["reason"] = "SCIP JSON must contain an object"
        return result

    try:
        if manifest.get("index_sha256") != _sha256_file(index_path):
            result["reason"] = "SCIP index hash mismatch"
            return result
        if manifest.get("json_sha256") != _sha256_file(json_path):
            result["reason"] = "SCIP JSON hash mismatch"
            return result
    except OSError:
        result["reason"] = "SCIP index state is unreadable"
        return result

    relative = _repository_relative_path(workspace, repository)
    current = repository_fingerprint(repository, relative)
    if manifest.get("repository_fingerprint") != current.get("fingerprint"):
        result["reason"] = "repository fingerprint mismatch"
        return result
    if manifest.get("git_head") != current.get("git_head"):
        result["reason"] = "Git HEAD mismatch"
        return result

    result.update(
        {
            "ready": True,
            "reason": "SCIP provenance matches repository state",
            "language": manifest.get("language"),
            "indexer": manifest.get("indexer"),
            "repository_fingerprint": current.get("fingerprint"),
            "git_head": current.get("git_head"),
        }
    )
    return result


def scip_ready(workspace_root: Path, repository_root: Path) -> bool:
    return bool(scip_status(workspace_root, repository_root).get("ready"))


def any_scip_ready(workspace_root: Path, config: dict | None = None) -> bool:
    root = Path(workspace_root).resolve()
    for repository in active_repository_roots(root, config or {}):
        if scip_ready(root, repository):
            return True
    return False


def _field(row: Mapping[str, Any], camel: str, snake: str) -> Any:
    if camel in row:
        return row[camel]
    return row.get(snake)


def _symbol_tail(raw: str) -> str:
    parts = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw)
    return parts[-1] if parts else raw


def _query_anchor(query: str) -> str:
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", query)
    if not identifiers:
        return ""
    distinctive = [
        token for token in identifiers
        if "_" in token or any(char.isupper() for char in token[1:])
    ]
    return (distinctive[-1] if distinctive else identifiers[-1]).casefold()


def _source_line(root: Path, relative: str, line: int) -> str:
    try:
        path = resolve_within_root(root, relative)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (PathOutsideWorkspace, OSError):
        return ""
    return lines[line].strip() if 0 <= line < len(lines) else ""


def items_from_scip_payload(
    root: Path,
    payload: Mapping[str, Any],
    query: str,
    symbol: str | None,
    changed_files: list[str] | None,
    limit: int,
    *,
    patterns: tuple[str, ...] = (),
) -> list[ContextItem]:
    documents = payload.get("documents")
    if not isinstance(documents, list) or limit <= 0:
        return []

    target = str(symbol or "").strip().casefold() or _query_anchor(query)
    changed = {str(path).replace("\\", "/") for path in (changed_files or [])}
    want_references = "references_to" in patterns
    results: list[ContextItem] = []

    for document in documents:
        if not isinstance(document, Mapping):
            continue
        relative = str(_field(document, "relativePath", "relative_path") or "").strip().replace("\\", "/")
        if not relative:
            continue
        try:
            resolve_within_root(root, relative)
        except (PathOutsideWorkspace, OSError):
            continue

        language = str(document.get("language") or "unknown")
        info_by_symbol: dict[str, Mapping[str, Any]] = {}
        raw_infos = document.get("symbols")
        if isinstance(raw_infos, list):
            for info in raw_infos:
                if isinstance(info, Mapping):
                    raw_symbol = str(info.get("symbol") or "")
                    if raw_symbol:
                        info_by_symbol[raw_symbol] = info

        occurrences = document.get("occurrences")
        if not isinstance(occurrences, list):
            continue
        for occurrence in occurrences:
            if not isinstance(occurrence, Mapping):
                continue
            raw_symbol = str(occurrence.get("symbol") or "").strip()
            if not raw_symbol:
                continue
            info = info_by_symbol.get(raw_symbol, {})
            display = str(_field(info, "displayName", "display_name") or "").strip() or _symbol_tail(raw_symbol)
            if target and target not in display.casefold() and target not in raw_symbol.casefold():
                continue

            raw_roles = _field(occurrence, "symbolRoles", "symbol_roles")
            try:
                roles = int(raw_roles or 0)
            except (TypeError, ValueError):
                roles = 0
            is_definition = bool(roles & 1)
            if want_references and is_definition:
                continue

            raw_range = occurrence.get("range")
            line = 0
            if isinstance(raw_range, list) and raw_range:
                try:
                    line = max(0, int(raw_range[0]))
                except (TypeError, ValueError):
                    line = 0
            role = "definition" if is_definition else "reference"
            pattern = "definition_of" if is_definition else "references_to"
            source = _source_line(root, relative, line)
            text = f"{relative}:{line + 1}: {source or display} [{role}] {display}"
            results.append(
                ContextItem(
                    "scip",
                    text,
                    10.0 if is_definition else 9.0 + (0.25 if relative in changed else 0.0),
                    False,
                    {
                        "path": relative,
                        "line": line + 1,
                        "language": language,
                        "symbol": raw_symbol,
                        "symbol_name": display,
                        "role": role,
                        "pattern": pattern,
                        "structural_valid": True,
                        "result_count": 1,
                    },
                )
            )
            if len(results) >= limit:
                return results
    return results


def scip_context(
    root: Path,
    query: str,
    symbol: str | None,
    changed_files: list[str] | None,
    limit: int,
    *,
    patterns: tuple[str, ...] = (),
) -> list[ContextItem]:
    repository = Path(root).resolve()
    workspace = find_workspace_root(repository)
    status = scip_status(workspace, repository)
    if not status.get("ready"):
        return []
    json_path = Path(str(status["json"]))
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    return items_from_scip_payload(
        repository,
        payload,
        query,
        symbol,
        changed_files,
        limit,
        patterns=patterns,
    )


def sync_scip_index(
    workspace_root: Path,
    repository_root: Path,
    *,
    language: str | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    try:
        data_dir = scip_data_dir(workspace, repository)
    except (PathOutsideWorkspace, OSError) as exc:
        return {"ready": False, "reason": f"unsafe SCIP state path: {exc}"}

    indexer = detect_indexer(repository, language)
    if indexer is None:
        return {
            "ready": False,
            "reason": "no unambiguous supported SCIP indexer detected",
        }

    scip_executable = shutil.which("scip")
    indexer_executable = shutil.which(indexer.executable)
    if scip_executable is None:
        return {"ready": False, "reason": "scip CLI is not installed"}
    if indexer_executable is None:
        return {
            "ready": False,
            "reason": f"{indexer.executable} is not installed",
            "language": indexer.language,
        }

    data_dir.mkdir(parents=True, exist_ok=True)
    central_index = data_dir / "index.scip"
    temporary_index = data_dir / "index.scip.tmp"
    try:
        temporary_index.unlink(missing_ok=True)
    except OSError as exc:
        return {"ready": False, "reason": f"cannot prepare SCIP output: {exc}"}

    command = [indexer_executable, *indexer.args]
    if indexer.language == "go":
        command = [
            indexer_executable,
            "--output",
            str(temporary_index),
            *indexer.args,
        ]
    else:
        command.extend(["--output", str(temporary_index)])

    try:
        indexed = subprocess.run(
            command,
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ready": False, "reason": str(exc), "language": indexer.language}

    if (
        indexed.returncode != 0
        or not temporary_index.is_file()
        or temporary_index.is_symlink()
    ):
        try:
            temporary_index.unlink(missing_ok=True)
        except OSError:
            pass
        message = (indexed.stderr or indexed.stdout).strip()[:500]
        return {
            "ready": False,
            "reason": message or "SCIP indexer did not create a safe index",
            "language": indexer.language,
        }

    try:
        os.replace(temporary_index, central_index)
    except OSError as exc:
        return {"ready": False, "reason": f"cannot publish SCIP index: {exc}"}

    try:
        printed = subprocess.run(
            [scip_executable, "print", "--json", str(central_index)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(timeout_seconds, 60),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ready": False, "reason": f"scip print failed: {exc}"}
    if printed.returncode != 0 or not printed.stdout.strip():
        return {
            "ready": False,
            "reason": (printed.stderr or "scip print returned no JSON").strip()[:500],
        }
    try:
        payload = json.loads(printed.stdout)
    except json.JSONDecodeError as exc:
        return {"ready": False, "reason": f"scip print returned invalid JSON: {exc.msg}"}
    if not isinstance(payload, dict):
        return {"ready": False, "reason": "scip print JSON must contain an object"}

    json_path = data_dir / "index.json"
    atomic_write_json(json_path, payload, sort_keys=True)
    relative = _repository_relative_path(workspace, repository)
    fingerprint = repository_fingerprint(repository, relative)
    manifest = {
        "manifest_schema": SCIP_MANIFEST_SCHEMA,
        "repository_relative_path": relative,
        "repository_fingerprint": fingerprint["fingerprint"],
        "git_head": fingerprint.get("git_head"),
        "language": indexer.language,
        "indexer": indexer.executable,
        "index_sha256": _sha256_file(central_index),
        "json_sha256": _sha256_file(json_path),
    }
    atomic_write_json(data_dir / "manifest.json", manifest, sort_keys=True)
    return scip_status(workspace, repository)
