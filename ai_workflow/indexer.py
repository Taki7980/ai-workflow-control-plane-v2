from __future__ import annotations
import ast, hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone

from .io_utils import atomic_write_text

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
    "get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH",
    "getmapping": "GET", "postmapping": "POST", "putmapping": "PUT", "deletemapping": "DELETE", "patchmapping": "PATCH", "requestmapping": "REQUEST",
}

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _state_entry(path: Path, digest: str) -> dict:
    stat = path.stat(); return {"sha256": digest, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}

def _stat_matches(path: Path, entry: dict) -> bool:
    if "size" not in entry or "mtime_ns" not in entry or not entry.get("sha256"): return False
    try: stat = path.stat()
    except OSError: return False
    return int(entry.get("size", -1)) == int(stat.st_size) and int(entry.get("mtime_ns", -1)) == int(stat.st_mtime_ns)

def iter_source(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SOURCE_EXTS: continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE for part in rel.parts): continue
        yield p, rel.as_posix()

def _python_symbols(text: str, rel: str, digest: str) -> list[dict] | None:
    try: tree = ast.parse(text)
    except SyntaxError: return None
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rows.append({"symbol": node.name, "file": rel, "line": int(node.lineno), "end_line": int(getattr(node, "end_lineno", node.lineno)), "kind": "class" if isinstance(node, ast.ClassDef) else "function", "parser": "python-ast", "sha256": digest})
    rows.sort(key=lambda row: (row["line"], row["symbol"])); return rows

def _route_from_line(line: str) -> tuple[str, str] | None:
    for route_re in CALL_ROUTE_RES:
        match = route_re.search(line)
        if match: return match.group(1).upper(), match.group(2)
    match = SPRING_ROUTE_RE.search(line)
    if not match: return None
    path_match = SPRING_PATH_RE.search(match.group("args"))
    if not path_match: return None
    return SPRING_METHODS.get(match.group("annotation").lower(), "REQUEST"), path_match.group("path")

def _parse_file(path: Path, rel: str, digest: str) -> tuple[list[dict], list[dict]]:
    symbols: list[dict] = []; endpoints: list[dict] = []
    try: text = path.read_text(encoding="utf-8", errors="replace"); lines = text.splitlines()
    except OSError: return symbols, endpoints
    ast_rows = _python_symbols(text, rel, digest) if path.suffix.lower() == ".py" else None
    if ast_rows is not None: symbols.extend(ast_rows)
    else:
        for i, line in enumerate(lines, 1):
            for sr in SYMBOL_RES:
                m = sr.search(line)
                if m:
                    symbols.append({"symbol": m.group(1), "file": rel, "line": i, "parser": "regex", "sha256": digest}); break
    for i, line in enumerate(lines, 1):
        route = _route_from_line(line)
        if route:
            method, route_path = route; endpoints.append({"method": method, "path": route_path, "file": rel, "line": i, "parser": "regex", "sha256": digest})
    return symbols, endpoints

def _write_jsonl(path: Path, rows: list[dict]):
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

def _write_index_state(path: Path, files: dict[str, dict]) -> None:
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": files}
    atomic_write_text(path, json.dumps(index_state, indent=2, sort_keys=True) + "\n")

def build_indexes(root: Path) -> dict:
    gen = root / "ai-workspace" / "generated"; gen.mkdir(parents=True, exist_ok=True)
    symbols, endpoints, state = [], [], {}; ast_files = 0
    for path, rel in iter_source(root):
        digest = sha256(path)
        try: state[rel] = _state_entry(path, digest)
        except OSError: continue
        new_sym, new_ep = _parse_file(path, rel, digest)
        if any(row.get("parser") == "python-ast" for row in new_sym): ast_files += 1
        symbols.extend(new_sym); endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols); _write_jsonl(gen / "endpoint-index.jsonl", endpoints); _write_index_state(gen / "index-state.json", state)
    return {"files": len(state), "symbols": len(symbols), "endpoints": len(endpoints), "ast_files": ast_files}

def load_state(root: Path) -> dict:
    path = root / "ai-workspace" / "generated" / "index-state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")); return data if data.get("version") == 2 else {}
    except (OSError, json.JSONDecodeError): return {}

def row_fresh(root: Path, row: dict, state: dict | None = None) -> bool:
    rel = row.get("file")
    if not rel: return True
    path = root / rel
    if not path.exists(): return False
    state = state or load_state(root); expected = (state.get("files", {}).get(rel) or {}).get("sha256")
    if not expected or row.get("sha256") != expected: return False
    try: return sha256(path) == expected
    except OSError: return False

def incremental_indexes(root: Path, strict_hash: bool = False) -> dict:
    gen = root / "ai-workspace" / "generated"; gen.mkdir(parents=True, exist_ok=True)
    old_state = load_state(root); old_files = old_state.get("files", {})
    def read_jsonl(p: Path) -> list[dict]:
        if not p.exists(): return []
        rows = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                try: rows.append(json.loads(line))
                except json.JSONDecodeError: pass
        return rows
    old_symbols = read_jsonl(gen / "symbol-index.jsonl"); old_endpoints = read_jsonl(gen / "endpoint-index.jsonl")
    current_files: dict[str, Path] = {rel: path for path, rel in iter_source(root)}
    changed: set[str] = set(); new_state: dict[str, dict] = {}; skipped = 0; stat_reused = 0; hashed = 0
    for rel, path in current_files.items():
        old_entry = old_files.get(rel) or {}
        if not strict_hash and _stat_matches(path, old_entry):
            try: new_state[rel] = _state_entry(path, str(old_entry["sha256"]))
            except OSError: changed.add(rel); continue
            skipped += 1; stat_reused += 1; continue
        try:
            digest = sha256(path); hashed += 1; new_state[rel] = _state_entry(path, digest)
        except OSError: changed.add(rel); continue
        if old_entry and old_entry.get("sha256") == digest: skipped += 1
        else: changed.add(rel)
    removed = set(old_files.keys()) - set(current_files.keys()); keep_files = set(current_files.keys()) - changed
    symbols = [r for r in old_symbols if r.get("file") in keep_files]; endpoints = [r for r in old_endpoints if r.get("file") in keep_files]; ast_files = 0
    for rel in sorted(changed):
        path = current_files.get(rel); entry = new_state.get(rel)
        if path is None or entry is None: continue
        new_sym, new_ep = _parse_file(path, rel, entry["sha256"])
        if any(row.get("parser") == "python-ast" for row in new_sym): ast_files += 1
        symbols.extend(new_sym); endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols); _write_jsonl(gen / "endpoint-index.jsonl", endpoints); _write_index_state(gen / "index-state.json", new_state)
    return {"files": len(new_state), "symbols": len(symbols), "endpoints": len(endpoints), "incremental": True, "strict_hash": bool(strict_hash), "changed": len(changed), "removed": len(removed), "skipped": skipped, "stat_reused": stat_reused, "hashed": hashed, "ast_files_changed": ast_files}
