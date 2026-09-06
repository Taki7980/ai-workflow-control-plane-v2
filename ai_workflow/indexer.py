from __future__ import annotations
import ast, hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone

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
ROUTE_RES = [
    re.compile(r"(?:@(?:app|router|bp|api_router)\.(get|post|put|delete|patch))\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"\b(?:router|app|r|e)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"@(?:Get|Post|Put|Delete|Patch|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\(\s*['\"]([^'\"]+)['\"]", re.I),
]

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def iter_source(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SOURCE_EXTS:
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE for part in rel.parts):
            continue
        yield p, rel.as_posix()


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
        for rr in ROUTE_RES:
            rm = rr.search(line)
            if rm:
                endpoints.append({"method": rm.group(1).upper(), "path": rm.group(2), "file": rel, "line": i, "parser": "regex", "sha256": digest})
                break
    return symbols, endpoints


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def build_indexes(root: Path) -> dict:
    gen = root / "ai-workspace" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    symbols, endpoints, state = [], [], {}
    ast_files = 0
    for path, rel in iter_source(root):
        digest = sha256(path)
        state[rel] = {"sha256": digest}
        new_sym, new_ep = _parse_file(path, rel, digest)
        if any(row.get("parser") == "python-ast" for row in new_sym):
            ast_files += 1
        symbols.extend(new_sym)
        endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols)
    _write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": state}
    (gen / "index-state.json").write_text(json.dumps(index_state, indent=2) + "\n", encoding="utf-8")
    return {"files": len(state), "symbols": len(symbols), "endpoints": len(endpoints), "ast_files": ast_files}

def load_state(root: Path) -> dict:
    path = root / "ai-workspace" / "generated" / "index-state.json"
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


def incremental_indexes(root: Path) -> dict:
    gen = root / "ai-workspace" / "generated"
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
    current_files: dict[str, tuple[Path, str]] = {rel: (path, "") for path, rel in iter_source(root)}
    changed: set[str] = set()
    new_state: dict[str, dict] = {}
    skipped = 0
    for rel, (path, _) in current_files.items():
        digest = sha256(path)
        new_state[rel] = {"sha256": digest}
        old_entry = old_files.get(rel)
        if old_entry and old_entry.get("sha256") == digest:
            skipped += 1
        else:
            changed.add(rel)
    removed = set(old_files.keys()) - set(current_files.keys())
    keep_files = set(current_files.keys()) - changed - removed
    symbols = [r for r in old_symbols if r.get("file") in keep_files]
    endpoints = [r for r in old_endpoints if r.get("file") in keep_files]
    ast_files = 0
    for rel in changed:
        path = current_files[rel][0]
        digest = new_state[rel]["sha256"]
        new_sym, new_ep = _parse_file(path, rel, digest)
        if any(row.get("parser") == "python-ast" for row in new_sym):
            ast_files += 1
        symbols.extend(new_sym)
        endpoints.extend(new_ep)
    _write_jsonl(gen / "symbol-index.jsonl", symbols)
    _write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": new_state}
    (gen / "index-state.json").write_text(json.dumps(index_state, indent=2) + "\n", encoding="utf-8")
    return {"files": len(new_state), "symbols": len(symbols), "endpoints": len(endpoints), "incremental": True, "changed": len(changed), "removed": len(removed), "skipped": skipped, "ast_files_changed": ast_files}
