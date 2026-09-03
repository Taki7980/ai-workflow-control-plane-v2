from __future__ import annotations
import ast, json, re, subprocess, shutil, concurrent.futures
from pathlib import Path
from .budget import ContextBudget, truncate
from .indexer import load_state, row_fresh, sha256
from .memory import search_memory
from .models import ContextItem, RouteDecision, Lane
from .providers import ProviderStatus
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, TokenizedDoc, tokenize


def _jsonl(path: Path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: continue
    return rows

def detect_changed_files(root: Path) -> list[str]:
    if not shutil.which("git"):
        return []
    try:
        p = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=4,
            check=False,
        )
        if p.returncode != 0 or not p.stdout.strip():
            return []
        changed = []
        for line in p.stdout.splitlines():
            line = line.strip()
            if not line or len(line) < 3:
                continue
            path_part = line[2:].strip().split(" -> ")[-1].strip('"')
            if path_part:
                changed.append(path_part)
        return changed
    except (OSError, subprocess.TimeoutExpired):
        return []

def _score(query: str, text: str) -> int:
    terms = {x for x in re.split(r"\W+", query.lower()) if len(x) >= 2}
    low = text.lower()
    return sum(1 for t in terms if t in low)

def resolve_test_files(changed_files: list[str]) -> list[dict]:
    results = []
    for f in changed_files:
        p = Path(f)
        stem, ext = p.stem, p.suffix
        if not ext or "test" in stem.lower() or "spec" in stem.lower():
            continue
        candidates = []
        if ext in {".py", ".rb", ".php"}:
            candidates = [f"test_{stem}{ext}", f"{stem}_test{ext}"]
        elif ext in {".js", ".ts", ".jsx", ".tsx"}:
            candidates = [f"{stem}.test{ext}", f"{stem}.spec{ext}", f"test_{stem}{ext}", f"{stem}_test{ext}"]
        elif ext == ".go":
            candidates = [f"{stem}_test.go"]
        elif ext in {".rs", ".java", ".cpp", ".cs"}:
            candidates = [f"{stem}Test{ext}", f"{stem}Tests{ext}", f"{stem}Spec{ext}", f"Test{stem}{ext}"]
        if candidates:
            results.append({"source": f, "candidates": candidates, "dir": p.parent.as_posix()})
    return results

def find_tests_for_changed(root: Path, changed_files: list[str]) -> list[ContextItem]:
    out = []
    state = load_state(root).get("files", {})
    resolved = resolve_test_files(changed_files)
    for r in resolved:
        for cand in r["candidates"]:
            # Check same dir
            cand_path = (Path(r["dir"]) / cand).as_posix()
            if cand_path in state:
                out.append(ContextItem("test_resolver", f"Detected test file: {cand_path} (for {r['source']})", 10.0))
                break
            # Check tests/ directory
            cand_test_dir = f"tests/{cand}"
            if cand_test_dir in state:
                out.append(ContextItem("test_resolver", f"Detected test file: {cand_test_dir} (for {r['source']})", 9.0))
                break
    return out

def _cap_items(items: list[ContextItem], chars: int, seen_keys: set[str] | None = None, query: str = "") -> list[ContextItem]:
    out = []
    used = 0
    seen = seen_keys if seen_keys is not None else set()
    
    # Submodular maximization via MMR if items are plenty and query is provided
    if query and len(items) > 1:
        bm25 = BM25Scorer()
        texts = [i.text for i in items]
        bm25.fit(texts, items)
        
        candidates = bm25.docs
        scores = [bm25.score_document(list(set(tokenize(query))), doc) for doc in candidates]
        
        # We fetch up to len(items) optimally sorted items
        ordered_items = maximal_marginal_relevance(tokenize(query), candidates, scores, lambda_param=0.5, max_items=len(items))
    else:
        # Fallback to greedy if no query or only 1 item
        ordered_items = items

    for item in ordered_items:
        if used >= chars:
            break
        k = item.dedupe_key
        if k in seen:
            continue
        seen.add(k)
        text, cut = truncate(item.text, chars - used)
        if text:
            meta = dict(item.metadata)
            if cut: meta["truncated"] = True
            out.append(ContextItem(item.source, text, item.score, item.stale, meta))
            used += len(text)
    return out

def hot_cache(root: Path, query: str, limit: int) -> list[ContextItem]:
    rows = []
    for name in ["hot-cache.jsonl", "incident-cache.jsonl"]:
        for r in _jsonl(root / "ai-workspace" / "generated" / name):
            text = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
            s = _score(query, text)
            if s: rows.append(ContextItem("hot_cache", text, float(s), False, {"cache": name}))
    rows.sort(key=lambda x: -x.score)
    return rows[:limit]



def _domain_hints(root: Path, query: str, limit: int) -> list[ContextItem]:
    path = root / "ai-workspace" / "agents" / "domain-manifest.yaml"
    if not path.exists():
        return []
    query_lower = query.lower()
    section = "main"
    module = ""
    current_key = ""
    current: dict[str, list[str]] = {}
    blocks: list[dict] = []

    def flush():
        nonlocal current, module, current_key
        if module and current:
            blocks.append({"section": section, "module": module, **current})
        current = {}
        current_key = ""

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        # Section header: top-level key (no indent)
        m_sec = re.match(r"^([A-Za-z0-9_.-]+):\s*$", line)
        if m_sec:
            flush()
            section = m_sec.group(1)
            module = ""
            continue
        # Module header: 2-space indent
        m_mod = re.match(r"^\s{2}([A-Za-z0-9_.-]+):\s*$", line)
        if m_mod:
            flush()
            module = m_mod.group(1)
            continue
        # Field with inline list or scalar: 4-space indent
        m_field = re.match(r"^\s{4}([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m_field and module:
            k = m_field.group(1)
            rest = m_field.group(2).strip()
            current_key = k
            if rest.startswith("[") and rest.endswith("]"):
                try:
                    val = ast.literal_eval(rest)
                    if isinstance(val, list):
                        current[k] = [str(x).strip() for x in val if str(x).strip()]
                except (SyntaxError, ValueError):
                    current[k] = [x.strip().strip("'\"") for x in rest[1:-1].split(",") if x.strip()]
            elif rest:
                current[k] = [x.strip().strip("'\"") for x in rest.split(",") if x.strip()]
            else:
                current[k] = []
            continue
        # List item under current field: 6-space indent or - item
        m_item = re.match(r"^\s+(?:-\s+)(.+)$", line)
        if m_item and module and current_key:
            val = m_item.group(1).strip().strip("'\"")
            if val:
                current.setdefault(current_key, []).append(val)
    flush()

    out = []
    for b in blocks:
        keywords = [str(x).lower() for x in b.get("keywords", [])]
        score = sum(1 for kw in keywords if kw and kw in query_lower)
        if not score:
            continue
        paths = []
        for k, value in b.items():
            if k in {"section", "module", "keywords"} or not isinstance(value, list):
                continue
            paths.extend(str(x) for x in value if "/" in str(x) or "\\" in str(x))
        payload = {"module": f"{b['section']}/{b['module']}", "paths": paths[:12], "keywords": b.get("keywords", [])}
        out.append(ContextItem("domain_manifest", json.dumps(payload, separators=(",", ":")), float(score)))
    out.sort(key=lambda x: -x.score)
    return out[:limit]


def _research_hits(root: Path, query: str, limit: int) -> list[ContextItem]:
    path = root / "ai-workspace" / "agents" / "research.md"
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = _score(query, line)
        if s:
            rows.append(ContextItem("research_cache", f"L{i}: {line.strip()}", float(s)))
    rows.sort(key=lambda x: -x.score)
    return rows[:limit]

def lightweight(root: Path, query: str, symbol: str | None, endpoint: str | None, limit: int, min_conf: float) -> list[ContextItem]:
    state = load_state(root)
    out: list[ContextItem] = []
    for r in _jsonl(root / "ai-workspace" / "generated" / "symbol-index.jsonl"):
        target = symbol or query
        s = 10 if symbol and r.get("symbol", "").lower() == symbol.lower() else _score(target, f"{r.get('symbol','')} {r.get('file','')}")
        if s:
            fresh = row_fresh(root, r, state)
            if fresh:
                out.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s), False, {"kind": "symbol"}))
    for r in _jsonl(root / "ai-workspace" / "generated" / "endpoint-index.jsonl"):
        target = endpoint or query
        s = 10 if endpoint and endpoint.lower() in r.get("path", "").lower() else _score(target, f"{r.get('method','')} {r.get('path','')} {r.get('file','')}")
        if s and row_fresh(root, r, state):
            out.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s), False, {"kind": "endpoint"}))
    out.extend(_domain_hints(root, query, limit))
    out.extend(_research_hits(root, query, limit))
    for m in search_memory(root, query, limit=limit, minimum_confidence=min_conf, exclude_stale=True):
        compact = {k: m.get(k) for k in ("id","type","summary","evidence","files","confidence")}
        out.append(ContextItem("durable_memory", json.dumps(compact, ensure_ascii=False, separators=(",", ":")), float(m.get("score", 0)), False))
    out.sort(key=lambda x: -x.score)
    return out[:limit]

def _run_crg(root: Path, args: list[str], timeout: int = 8) -> str | None:
    if not shutil.which("code-review-graph"):
        return None
    try:
        p = subprocess.run(["code-review-graph", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None

def crg_context(root: Path, query: str, symbol: str | None, changed_files: list[str] | None, limit: int) -> list[ContextItem]:
    results: list[ContextItem] = []
    if symbol:
        for pattern in ("callers_of", "callees_of", "tests_for"):
            text = _run_crg(root, ["query", pattern, symbol])
            if text:
                results.append(ContextItem("code_review_graph", text, 9.0, False, {"pattern": pattern}))
                if len(results) >= limit: return results
    if changed_files:
        text = _run_crg(root, ["impact", "--files", *changed_files])
        if text: results.append(ContextItem("code_review_graph", text, 8.0, False, {"pattern": "impact"}))
    if not results:
        text = _run_crg(root, ["search", query, "--limit", str(limit)])
        if text: results.append(ContextItem("code_review_graph", text, 5.0, False, {"pattern": "search"}))
    return results[:limit]

def targeted_source(root: Path, query: str, limit: int) -> list[ContextItem]:
    terms = [x for x in re.split(r"\W+", query) if len(x) >= 4][:4]
    if not terms:
        return []
    pattern = "|".join(re.escape(t) for t in terms)
    if shutil.which("rg"):
        try:
            p = subprocess.run(["rg", "-n", "--no-heading", "-m", "2",
                "--glob", "!ai-workspace/generated/**", "--glob", "!.ai/**", "--glob", "!**/.git/**", "--glob", "!**/node_modules/**",
                pattern, "."], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=6, check=False)
            lines = [x for x in p.stdout.splitlines() if not any(seg in x for seg in ("ai-workspace/generated", ".git/"))][:limit]
            return [ContextItem("targeted_source", x, 1.0) for x in lines]
        except (OSError, subprocess.TimeoutExpired):
            pass
    out = []
    excluded = {".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__"}
    for p in root.rglob("*"):
        if len(out) >= limit: break
        if not p.is_file() or any(x in excluded for x in p.relative_to(root).parts) or "ai-workspace/generated" in p.relative_to(root).as_posix(): continue
        try:
            if p.stat().st_size > 500_000: continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if re.search(pattern, line, re.I):
                    out.append(ContextItem("targeted_source", f"{p.relative_to(root).as_posix()}:{i}: {line.strip()}", 1.0))
                    if len(out) >= limit: break
        except OSError: continue
    return out

def gather(root: Path, query: str, decision: RouteDecision, budget: ContextBudget, config: dict, providers: ProviderStatus, symbol: str | None = None, endpoint: str | None = None, changed_files: list[str] | None = None) -> list[ContextItem]:
    limit = int(config["context"].get("max_results_per_source", 6))
    items: list[ContextItem] = []
    seen_keys: set[str] = set()

    crg_cfg = config["context"]["crg"]
    indexed_files = len(load_state(root).get("files", {}))
    min_files = int(crg_cfg.get("min_source_files", 250))
    changed_threshold = int(crg_cfg.get("changed_files_threshold", 3))
    broad_change = len(changed_files or []) >= changed_threshold
    large_full = decision.lane == Lane.FULL and indexed_files >= min_files
    wants_crg = providers.code_review_graph and crg_cfg.get("mode", "auto") != "off" and (
        decision.structural_context or broad_change or large_full
    )

    # Step 0: Test resolver for changed files
    if changed_files:
        test_items = find_tests_for_changed(root, changed_files)
        items += _cap_items(test_items, 600, seen_keys)

    # Priority 0: Hot cache
    hot = hot_cache(root, query, limit)
    items += _cap_items(hot, budget.source_chars.get("hot_cache", 1000), seen_keys, query=query)
    
    # Run async gathering for remaining sources
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f_light = executor.submit(lightweight, root, query, symbol, endpoint, limit, float(config["memory"].get("minimum_confidence", 0.55)))
        f_crg = executor.submit(crg_context, root, query, symbol, changed_files, limit) if wants_crg else None
        f_source = executor.submit(targeted_source, root, query, int(config["context"]["targeted_search"].get("max_matches", 12)))

        # Priority 1: Lightweight index + domain hints + research + memory
        remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
        light_budget = max(budget.source_chars.get("lightweight", 2000), remaining // 2)
        light = f_light.result()
        items += _cap_items(light, min(remaining, light_budget), seen_keys, query=query)

        # Priority 2: Code Review Graph (CRG)
        crg_items = f_crg.result() if f_crg else []
        if wants_crg and crg_items:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            crg_budget = min(remaining, budget.source_chars.get("crg", 3000))
            items += _cap_items(crg_items, crg_budget, seen_keys, query=query)

        # Priority 3: Targeted Source Fallback
        code_sources = {"lightweight_index", "domain_manifest", "code_review_graph"}
        has_code_evidence = any(i.source in code_sources for i in items)
        needs_structural_fallback = decision.structural_context and not crg_items
        needs_mutation_fallback = decision.lane != Lane.ANSWER and not has_code_evidence
        
        if not items or needs_structural_fallback or needs_mutation_fallback:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            if remaining > 80:
                source_items = f_source.result()
                items += _cap_items(source_items, remaining, seen_keys, query=query)


    # Final hard limit check against total context budget
    final_items: list[ContextItem] = []
    used_chars = 0
    final_seen: set[str] = set()
    for item in items:
        if used_chars >= budget.context_chars:
            break
        k = item.dedupe_key
        if k in final_seen:
            continue
        final_seen.add(k)
        text, cut = truncate(item.text, budget.context_chars - used_chars)
        if text:
            meta = dict(item.metadata)
            if cut:
                meta["truncated"] = True
            final_items.append(ContextItem(item.source, text, item.score, item.stale, meta))
            used_chars += len(text)
    return final_items
