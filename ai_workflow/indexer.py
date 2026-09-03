from __future__ import annotations
import hashlib, json, re
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

def build_indexes(root: Path) -> dict:
    gen = root / "ai-workspace" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    symbols, endpoints, state = [], [], {}
    for path, rel in iter_source(root):
        digest = sha256(path)
        state[rel] = {"sha256": digest}
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for sr in SYMBOL_RES:
                m = sr.search(line)
                if m:
                    symbols.append({"symbol": m.group(1), "file": rel, "line": i, "sha256": digest})
                    break
            for rr in ROUTE_RES:
                rm = rr.search(line)
                if rm:
                    endpoints.append({"method": rm.group(1).upper(), "path": rm.group(2), "file": rel, "line": i, "sha256": digest})
                    break
    def write_jsonl(path: Path, rows: list[dict]):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    write_jsonl(gen / "symbol-index.jsonl", symbols)
    write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": state}
    (gen / "index-state.json").write_text(json.dumps(index_state, indent=2) + "\n", encoding="utf-8")
    return {"files": len(state), "symbols": len(symbols), "endpoints": len(endpoints)}

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


def _parse_file(path: Path, rel: str, digest: str) -> tuple[list[dict], list[dict]]:
    symbols: list[dict] = []
    endpoints: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return symbols, endpoints
    for i, line in enumerate(lines, 1):
        for sr in SYMBOL_RES:
            m = sr.search(line)
            if m:
                symbols.append({"symbol": m.group(1), "file": rel, "line": i, "sha256": digest})
                break
        for rr in ROUTE_RES:
            rm = rr.search(line)
            if rm:
                endpoints.append({"method": rm.group(1).upper(), "path": rm.group(2), "file": rel, "line": i, "sha256": digest})
                break
    return symbols, endpoints


def incremental_indexes(root: Path) -> dict:
    gen = root / "ai-workspace" / "generated"
    gen.mkdir(parents=True, exist_ok=True)

    old_state = load_state(root)
    old_files = old_state.get("files", {})

    # Load existing indexes
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

    # Determine what exists now
    current_files: dict[str, tuple[Path, str]] = {}
    for path, rel in iter_source(root):
        current_files[rel] = (path, "")

    # Detect changed, new, removed
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

    # Filter old index entries: keep entries from unchanged files
    keep_files = set(current_files.keys()) - changed - removed
    symbols = [r for r in old_symbols if r.get("file") in keep_files]
    endpoints = [r for r in old_endpoints if r.get("file") in keep_files]

    # Parse changed/new files
    for rel in changed:
        path = current_files[rel][0]
        digest = new_state[rel]["sha256"]
        new_sym, new_ep = _parse_file(path, rel, digest)
        symbols.extend(new_sym)
        endpoints.extend(new_ep)

    def write_jsonl(p: Path, rows: list[dict]):
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    write_jsonl(gen / "symbol-index.jsonl", symbols)
    write_jsonl(gen / "endpoint-index.jsonl", endpoints)
    index_state = {"version": 2, "generated_at": datetime.now(timezone.utc).isoformat(), "files": new_state}
    (gen / "index-state.json").write_text(json.dumps(index_state, indent=2) + "\n", encoding="utf-8")
    return {
        "files": len(new_state), "symbols": len(symbols), "endpoints": len(endpoints),
        "incremental": True, "changed": len(changed), "removed": len(removed), "skipped": skipped,
    }
