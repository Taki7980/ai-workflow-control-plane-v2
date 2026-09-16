from __future__ import annotations
import ast, hashlib, json, os, re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .io_utils import atomic_write_json, atomic_write_jsonl
from .repository_registry import is_git_repository
from .workspace import active_repository_roots

SOURCE_EXTS = {
    ".py", ".rs", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala", ".sql", ".vue", ".svelte",
}
EXCLUDE = {".git", "node_modules", "venv", ".venv", "dist", "build", "bin", "obj", "__pycache__", "ai-workspace", ".ai", ".agents"}
SYMBOL_RES = [
    re.compile(r"^\s*(?:(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|fn|function|class|struct|interface|type|enum|pub\s+fn|pub\s+struct|pub\(crate\)\s+fn))\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_]+)\s*=>"),
    re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\("),
]
SYMBOL_RE = SYMBOL_RES[0]
CALL_ROUTE_RES = [
    re.compile(r"(?:@(?:app|router|bp|api_router)\.(get|post|put|delete|patch))\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"\b(?:router|app|r|e)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
]
SPRING_ROUTE_RE = re.compile(
    r"@(?P<annotation>Get|Post|Put|Delete|Patch|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\((?P<args>[^)]*)\)",
    re.I,
)
SPRING_PATH_RE = re.compile(r"(?:\b(?:value|path)\s*=\s*)?['\"](?P<path>/[^'\"]*)['\"]")
SPRING_METHODS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "getmapping": "GET",
    "postmapping": "POST",
    "putmapping": "PUT",
    "deletemapping": "DELETE",
    "patchmapping": "PATCH",
    "requestmapping": "REQUEST",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _state_entry(path: Path, digest: str) -> dict:
    stat = path.stat()
    return {"sha256": digest, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _stat_matches(path: Path, entry: dict) -> bool:
    if "size" not in entry or "mtime_ns" not in entry or not entry.get("sha256"):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return int(entry.get("size", -1)) == int(stat.st_size) and int(entry.get("mtime_ns", -1)) == int(stat.st_mtime_ns)


def _find_control_root(start: Path) -> Path:
    current = Path(start).resolve()
    for candidate in (current, *current.parents):
        if (
            candidate
            / "ai-workspace"
            / "config"
            / "control-plane.json"
        ).is_file():
            return candidate
    return current


def _repo_key(relative_path: str) -> str:
    value = relative_path.strip().replace("\\", "/")
    if value in {"", "."}:
        return "root"
    parts: list[str] = []
    for raw in value.split("/"):
        cleaned = re.sub(
            r"[^A-Za-z0-9._-]+",
            "-",
            raw,
        ).strip(".-_")
        parts.append(cleaned or "repo")
    return "__".join(parts)


def index_data_dir(
    repository_root: Path,
    workspace_root: Path | None = None,
) -> Path:
    """Return the central lightweight-index directory for one repository."""

    repository = Path(repository_root).resolve()
    workspace = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else _find_control_root(repository)
    )
    if repository == workspace:
        return workspace / "ai-workspace" / "generated"
    try:
        relative = repository.relative_to(workspace).as_posix()
    except ValueError:
        # Legacy explicit external roots retain their historical local state.
        return repository / "ai-workspace" / "generated"
    return (
        workspace
        / "ai-workspace"
        / "indexes"
        / _repo_key(relative)
    )


def nested_repository_paths(root: Path) -> list[str]:
    """Return nested Git roots relative to one repository root."""

    base = Path(root).resolve()
    found: list[str] = []
    for directory, dirnames, _filenames in os.walk(base):
        current = Path(directory)
        filtered: list[str] = []
        for name in dirnames:
            if name in EXCLUDE:
                continue
            candidate = current / name
            if is_git_repository(candidate):
                try:
                    found.append(
                        candidate.resolve().relative_to(base).as_posix()
                    )
                except (OSError, ValueError):
                    pass
                continue
            filtered.append(name)
        dirnames[:] = filtered
    return sorted(set(found))


def iter_source(root: Path):
    base = Path(root).resolve()
    for directory, dirnames, filenames in os.walk(base):
        current = Path(directory)
        filtered: list[str] = []
        for name in dirnames:
            if name in EXCLUDE:
                continue
            candidate = current / name
            if is_git_repository(candidate):
                continue
            filtered.append(name)
        dirnames[:] = filtered

        for name in filenames:
            path = current / name
            if path.suffix.lower() not in SOURCE_EXTS:
                continue
            try:
                rel = path.relative_to(base)
            except ValueError:
                continue
            if any(part in EXCLUDE for part in rel.parts):
                continue
            yield path, rel.as_posix()


def _python_symbols(text: str, rel: str, digest: str) -> list[dict] | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rows.append({
                "symbol": node.name,
                "file": rel,
                "line": int(node.lineno),
                "end_line": int(getattr(node, "end_lineno", node.lineno)),
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "parser": "python-ast",
                "sha256": digest,
            })
    rows.sort(key=lambda row: (row["line"], row["symbol"]))
    return rows


def _route_from_line(line: str) -> tuple[str, str] | None:
    for route_re in CALL_ROUTE_RES:
        match = route_re.search(line)
        if match:
            return match.group(1).upper(), match.group(2)
    match = SPRING_ROUTE_RE.search(line)
    if not match:
        return None
    path_match = SPRING_PATH_RE.search(match.group("args"))
    if not path_match:
        return None
    method = SPRING_METHODS.get(match.group("annotation").lower(), "REQUEST")
    return method, path_match.group("path")


def _parse_file(path: Path, rel: str, digest: str) -> tuple[list[dict], list[dict]]:
    symbols: list[dict] = []
    endpoints: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
    except OSError:
        return symbols, endpoints

    ast_rows = _python_symbols(text, rel, digest) if path.suffix.lower() == ".py" else None
    if ast_rows is not None:
        symbols.extend(ast_rows)
    else:
        for i, line in enumerate(lines, 1):
            for sr in SYMBOL_RES:
                m = sr.search(line)
                if m:
                    symbols.append({"symbol": m.group(1), "file": rel, "line": i, "parser": "regex", "sha256": digest})
                    break

    for i, line in enumerate(lines, 1):
        route = _route_from_line(line)
        if route:
            method, route_path = route
            endpoints.append({"method": method, "path": route_path, "file": rel, "line": i, "parser": "regex", "sha256": digest})
    return symbols, endpoints


def _write_jsonl(path: Path, rows: list[dict]):
    atomic_write_jsonl(path, rows)


def _write_index_state(path: Path, files: dict[str, dict]) -> None:
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": files}
    atomic_write_json(path, index_state, sort_keys=True)


def build_indexes(root: Path) -> dict:
    gen = index_data_dir(root)
    gen.mkdir(parents=True, exist_ok=True)
    symbols, endpoints, state = [], [], {}
    ast_files = 0
    for path, rel in iter_source(root):
        digest = sha256(path)
        try:
            state[rel] = _state_entry(path, digest)
        except OSError:
            continue
        new_sym, new_ep = _parse_file(path, rel, digest)
        if any(row.get("parser") == "python-ast" for row in new_sym):
            ast_files += 1
        symbols.extend(new_sym)
        endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols)
    _write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    _write_index_state(gen / "index-state.json", state)
    return {"files": len(state), "symbols": len(symbols), "endpoints": len(endpoints), "ast_files": ast_files}


def load_state(root: Path) -> dict:
    path = index_data_dir(root) / "index-state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data.get("version") == 2 else {}
    except (OSError, json.JSONDecodeError):
        return {}


def row_fresh(root: Path, row: dict, state: dict | None = None) -> bool:
    rel = row.get("file")
    if not rel:
        return True
    path = root / rel
    if not path.exists():
        return False
    state = state or load_state(root)
    expected = (state.get("files", {}).get(rel) or {}).get("sha256")
    if not expected or row.get("sha256") != expected:
        return False
    try:
        return sha256(path) == expected
    except OSError:
        return False


def incremental_indexes(root: Path, strict_hash: bool = False) -> dict:
    gen = index_data_dir(root)
    gen.mkdir(parents=True, exist_ok=True)
    old_state = load_state(root)
    old_files = old_state.get("files", {})

    def read_jsonl(p: Path) -> list[dict]:
        if not p.exists():
            return []
        rows = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows

    old_symbols = read_jsonl(gen / "symbol-index.jsonl")
    old_endpoints = read_jsonl(gen / "endpoint-index.jsonl")
    current_files: dict[str, Path] = {rel: path for path, rel in iter_source(root)}
    changed: set[str] = set()
    new_state: dict[str, dict] = {}
    skipped = 0
    stat_reused = 0
    hashed = 0

    for rel, path in current_files.items():
        old_entry = old_files.get(rel) or {}
        if not strict_hash and _stat_matches(path, old_entry):
            try:
                new_state[rel] = _state_entry(path, str(old_entry["sha256"]))
            except OSError:
                changed.add(rel)
                continue
            skipped += 1
            stat_reused += 1
            continue

        try:
            digest = sha256(path)
            hashed += 1
            new_state[rel] = _state_entry(path, digest)
        except OSError:
            changed.add(rel)
            continue
        if old_entry and old_entry.get("sha256") == digest:
            skipped += 1
        else:
            changed.add(rel)

    removed = set(old_files.keys()) - set(current_files.keys())
    keep_files = set(current_files.keys()) - changed
    symbols = [r for r in old_symbols if r.get("file") in keep_files]
    endpoints = [r for r in old_endpoints if r.get("file") in keep_files]
    ast_files = 0
    for rel in sorted(changed):
        changed_path = current_files.get(rel)
        entry = new_state.get(rel)
        if changed_path is None or entry is None:
            continue
        digest = entry["sha256"]
        new_sym, new_ep = _parse_file(changed_path, rel, digest)
        if any(row.get("parser") == "python-ast" for row in new_sym):
            ast_files += 1
        symbols.extend(new_sym)
        endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols)
    _write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    _write_index_state(gen / "index-state.json", new_state)
    return {
        "files": len(new_state),
        "symbols": len(symbols),
        "endpoints": len(endpoints),
        "incremental": True,
        "strict_hash": bool(strict_hash),
        "changed": len(changed),
        "removed": len(removed),
        "skipped": skipped,
        "stat_reused": stat_reused,
        "hashed": hashed,
        "ast_files_changed": ast_files,
    }


def _repository_relative_path(
    workspace_root: Path,
    repository_root: Path,
) -> str:
    workspace = Path(workspace_root).resolve()
    repository = Path(repository_root).resolve()
    if repository == workspace:
        return "."
    try:
        return repository.relative_to(workspace).as_posix()
    except ValueError:
        return f"legacy:{repository.name}"


def index_workspace(
    root: Path,
    config: dict,
    *,
    mode: str = "auto",
    strict_hash: bool = False,
) -> dict:
    """Index every active repository while keeping repository state isolated."""

    normalized = str(mode or "auto").lower()
    if normalized not in {"auto", "full", "incremental", "none"}:
        raise ValueError(
            "index mode must be auto, full, incremental, or none"
        )

    workspace = Path(root).resolve()
    repositories = active_repository_roots(workspace, config)
    rows: list[dict] = []
    totals = {
        "files": 0,
        "symbols": 0,
        "endpoints": 0,
        "ast_files": 0,
    }
    effective_modes: list[str] = []

    for repository in repositories:
        relative = _repository_relative_path(workspace, repository)
        data_dir = index_data_dir(repository, workspace)
        effective = normalized
        if normalized == "auto":
            effective = (
                "incremental"
                if (data_dir / "index-state.json").is_file()
                else "full"
            )
        effective_modes.append(effective)

        result: dict[str, Any]
        if effective == "none":
            result = {
                "files": 0,
                "symbols": 0,
                "endpoints": 0,
                "skipped": True,
                "reason": "disabled",
            }
        elif effective == "incremental":
            result = incremental_indexes(
                repository,
                strict_hash=strict_hash,
            )
        else:
            result = build_indexes(repository)

        for key in totals:
            totals[key] += int(result.get(key, 0) or 0)
        rows.append(
            {
                "relative_path": relative,
                "repository_root": str(repository),
                "index_dir": str(data_dir),
                "mode": effective,
                **result,
            }
        )

    distinct_modes = set(effective_modes)
    aggregate_mode = (
        "skipped"
        if normalized == "none"
        else next(iter(distinct_modes))
        if len(distinct_modes) == 1
        else "mixed"
    )
    result = {
        "mode": aggregate_mode,
        "repository_count": len(rows),
        "repositories": rows,
        **totals,
    }
    if normalized == "none":
        result["reason"] = "disabled"
    return result
