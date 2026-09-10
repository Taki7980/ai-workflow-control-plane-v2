from __future__ import annotations
import ast, json, re, subprocess, shutil, concurrent.futures
from pathlib import Path
from .budget import ContextBudget, truncate
from .indexer import load_state, row_fresh, sha256
from .memory import search_memory
from .models import ContextItem, RouteDecision, Lane
from .providers import ProviderStatus
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, reciprocal_rank_fusion, tokenize


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
    return len(set(tokenize(query)) & set(tokenize(text)))


_LOW_INFORMATION_QUERY_TOKENS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does",
    "for", "from", "how", "in", "is", "it", "of", "on", "or", "should",
    "the", "to", "we", "where", "whether", "with",
})


def _semantic_overlap_score(query: str, text: str) -> int:
    query_tokens = {
        token for token in tokenize(query)
        if token not in _LOW_INFORMATION_QUERY_TOKENS
    }
    return len(query_tokens & set(tokenize(text)))

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

def _accepted_child_repository_paths(workspace_root: Path, config: dict) -> tuple[str, ...]:
    from .workspace import workspace_roots

    root = Path(workspace_root).resolve()
    paths: list[str] = []
    for candidate in workspace_roots(root, config):
        candidate = Path(candidate).resolve()
        if candidate == root:
            continue
        try:
            rel = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel and rel != ".":
            paths.append(rel)
    return tuple(sorted(set(paths)))


def _scope_index_row(
    row: dict,
    repository_path: str,
    child_repository_paths: tuple[str, ...] = (),
) -> tuple[dict, str] | None:
    original = str(row.get("file", "")).replace("\\", "/").lstrip("./")
    if not original:
        return dict(row), ""
    repo = str(repository_path or ".").replace("\\", "/").strip("/") or "."
    if repo == ".":
        if any(original.startswith(path.rstrip("/") + "/") for path in child_repository_paths):
            return None
        local = original
    elif repo.startswith("legacy:"):
        return None
    else:
        prefix = repo.rstrip("/") + "/"
        if not original.startswith(prefix):
            return None
        local = original[len(prefix):]
        if not local:
            return None
    scoped = dict(row)
    scoped["file"] = local
    return scoped, original


def _state_key(repository_path: str, local_path: str) -> str:
    local = str(local_path).replace("\\", "/").lstrip("./")
    repo = str(repository_path or ".").replace("\\", "/").strip("/") or "."
    if repo == "." or repo.startswith("legacy:"):
        return local
    return f"{repo.rstrip('/')}/{local}" if local else repo


def _scoped_row_fresh(root: Path, row: dict, original_file: str, state: dict) -> bool:
    local = str(row.get("file", ""))
    if not local:
        return True
    path = Path(root) / local
    expected = ((state.get("files") or {}).get(original_file) or {}).get("sha256")
    if not expected or row.get("sha256") != expected or not path.is_file():
        return False
    try:
        return sha256(path) == expected
    except OSError:
        return False


def _scoped_index_file_count(state: dict, repository_path: str, child_repository_paths: tuple[str, ...]) -> int:
    count = 0
    for file in (state.get("files") or {}):
        scoped = _scope_index_row({"file": file}, repository_path, child_repository_paths)
        if scoped is not None:
            count += 1
    return count


def find_tests_for_changed(
    root: Path,
    changed_files: list[str],
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> list[ContextItem]:
    index_root = Path(workspace_root).resolve() if workspace_root is not None else Path(root).resolve()
    state = load_state(index_root)
    known = state.get("files", {})
    results = []
    seen = set()
    for changed in changed_files:
        p = Path(changed)
        stem = p.stem
        candidates = [
            p.with_name(f"test_{p.name}"), p.with_name(f"{stem}_test{p.suffix}"),
            Path("tests") / f"test_{p.name}", Path("test") / f"{stem}_test{p.suffix}",
            Path("__tests__") / f"{stem}.test{p.suffix}",
        ]
        for cand in candidates:
            rel = cand.as_posix()
            key = _state_key(repository_path, rel)
            if (key in known or (Path(root) / rel).is_file()) and rel not in seen:
                seen.add(rel)
                results.append(ContextItem("test_resolver", rel, 7.0, False, {"changed_file": changed, "path": rel}))
    return results


def _cap_items(items: list[ContextItem], chars: int, seen_keys: set[str] | None = None, query: str = "") -> list[ContextItem]:
    out = []
    used = 0
    seen = seen_keys if seen_keys is not None else set()
    
    # Fuse source-provided ranks with lexical ranks, then diversify relevant hits.
    if query and len(items) > 1:
        bm25 = BM25Scorer()
        bm25.fit([item.text for item in items], items)
        lexical_rank = [item for _, item in bm25.rank(query)]
        source_rank = sorted(
            (item for item in items if item.score > 0),
            key=lambda item: -item.score,
        )
        fused = reciprocal_rank_fusion(
            [source_rank, lexical_rank],
            key=lambda item: item.dedupe_key,
        )
        fused_items = [item for _, item in fused]
        fused_scores = [score for score, _ in fused]
        if fused_items:
            fused_bm25 = BM25Scorer()
            fused_bm25.fit([item.text for item in fused_items], fused_items)
            ordered_items = maximal_marginal_relevance(
                tokenize(query),
                fused_bm25.docs,
                fused_scores,
                lambda_param=0.7,
                max_items=len(fused_items),
            )
        else:
            ordered_items = []
    else:
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
            out.append(ContextItem(item.source, text, item.score, item.stale, meta, dict(item.provenance)))
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

def lightweight(
    root: Path,
    query: str,
    symbol: str | None,
    endpoint: str | None,
    limit: int,
    min_conf: float,
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
    child_repository_paths: tuple[str, ...] = (),
) -> list[ContextItem]:
    index_root = Path(workspace_root).resolve() if workspace_root is not None else Path(root).resolve()
    state = load_state(index_root)
    use_scoped_freshness = workspace_root is not None or repository_path != "." or bool(child_repository_paths)
    out: list[ContextItem] = []
    for raw in _jsonl(index_root / "ai-workspace/generated/symbol-index.jsonl"):
        mapped = _scope_index_row(raw, repository_path, child_repository_paths)
        if mapped is None:
            continue
        row, original = mapped
        target = symbol or query
        score = 10 if symbol and row.get("symbol", "").lower() == symbol.lower() else _semantic_overlap_score(target, f"{row.get('symbol','')} {row.get('file','')}")
        fresh = _scoped_row_fresh(root, row, original, state) if use_scoped_freshness else row_fresh(root, row, state)
        if score and fresh:
            out.append(ContextItem("lightweight_index", json.dumps(row, separators=(",", ":")), float(score), False, {"kind": "symbol"}))
    for raw in _jsonl(index_root / "ai-workspace/generated/endpoint-index.jsonl"):
        mapped = _scope_index_row(raw, repository_path, child_repository_paths)
        if mapped is None:
            continue
        row, original = mapped
        target = endpoint or query
        score = 10 if endpoint and endpoint.lower() in row.get("path", "").lower() else _semantic_overlap_score(target, f"{row.get('method','')} {row.get('path','')} {row.get('file','')}")
        fresh = _scoped_row_fresh(root, row, original, state) if use_scoped_freshness else row_fresh(root, row, state)
        if score and fresh:
            out.append(ContextItem("lightweight_index", json.dumps(row, separators=(",", ":")), float(score), False, {"kind": "endpoint"}))
    out.extend(_domain_hints(index_root, query, limit))
    out.extend(_research_hits(index_root, query, limit))
    for memory in search_memory(index_root, query, limit=limit, minimum_confidence=min_conf, exclude_stale=True):
        compact = {key: memory.get(key) for key in ("id", "type", "summary", "evidence", "files", "confidence")}
        out.append(ContextItem("durable_memory", json.dumps(compact, ensure_ascii=False, separators=(",", ":")), float(memory.get("score", 0)), False))
    out.sort(key=lambda item: -item.score)
    if len(out) <= limit or not query:
        return out[:limit]

    cutoff_score = out[limit - 1].score
    stronger = [item for item in out if item.score > cutoff_score]
    tied = [item for item in out if item.score == cutoff_score]
    slots = limit - len(stronger)
    if slots <= 0 or len(tied) <= slots:
        return out[:limit]

    bm25 = BM25Scorer()
    bm25.fit([item.text for item in tied], tied)
    lexical_scores = {id(item): score for score, item in bm25.rank(query)}
    selected = sorted(
        tied,
        key=lambda item: (
            -lexical_scores.get(id(item), 0.0),
            item.dedupe_key,
        ),
    )[:slots]
    selected_ids = {id(item) for item in selected}
    return stronger + [item for item in tied if id(item) in selected_ids]


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

def gather(
    root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: list[str] | None = None,
    *,
    workspace_root: Path | None = None,
    repository_path: str = ".",
) -> list[ContextItem]:
    root = Path(root).resolve()
    index_root = Path(workspace_root).resolve() if workspace_root is not None else root
    child_paths = _accepted_child_repository_paths(index_root, config) if repository_path == "." else ()
    limit = int(config["context"].get("max_results_per_source", 6))
    items: list[ContextItem] = []
    seen_keys: set[str] = set()

    crg_cfg = config["context"]["crg"]
    index_state = load_state(index_root)
    indexed_files = _scoped_index_file_count(index_state, repository_path, child_paths)
    min_files = int(crg_cfg.get("min_source_files", 250))
    changed_threshold = int(crg_cfg.get("changed_files_threshold", 3))
    broad_change = len(changed_files or []) >= changed_threshold
    large_full = decision.lane == Lane.FULL and indexed_files >= min_files
    wants_crg = providers.code_review_graph and crg_cfg.get("mode", "auto") != "off" and (
        decision.structural_context or broad_change or large_full
    )

    if changed_files:
        test_items = find_tests_for_changed(
            root,
            changed_files,
            workspace_root=index_root,
            repository_path=repository_path,
        )
        items += _cap_items(test_items, 600, seen_keys)
    hot = hot_cache(index_root, query, limit)
    items += _cap_items(hot, budget.source_chars.get("hot_cache", 1000), seen_keys, query=query)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_light = executor.submit(
            lightweight,
            root,
            query,
            symbol,
            endpoint,
            limit,
            float(config["memory"].get("minimum_confidence", 0.55)),
            workspace_root=index_root,
            repository_path=repository_path,
            child_repository_paths=child_paths,
        )
        f_crg = executor.submit(crg_context, root, query, symbol, changed_files, limit) if wants_crg else None

        remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
        light_budget = budget.source_chars.get("lightweight", 2000)
        light = f_light.result()
        items += _cap_items(light, min(remaining, light_budget), seen_keys, query=query)

        crg_items = f_crg.result() if f_crg else []
        if wants_crg and crg_items:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            crg_budget = min(remaining, budget.source_chars.get("crg", 3000))
            items += _cap_items(crg_items, crg_budget, seen_keys, query=query)

        code_sources = {"lightweight_index", "domain_manifest", "code_review_graph"}
        has_code_evidence = any(item.source in code_sources and _score(query, item.text) > 0 for item in items)
        needs_structural_fallback = decision.structural_context and not crg_items
        needs_mutation_fallback = decision.lane != Lane.ANSWER and not has_code_evidence
        if not items or needs_structural_fallback or needs_mutation_fallback:
            remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
            if remaining > 80:
                source_items = targeted_source(
                    root,
                    query,
                    int(config["context"]["targeted_search"].get("max_matches", 12)),
                )
                items += _cap_items(source_items, remaining, seen_keys, query=query)

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
            final_items.append(ContextItem(item.source, text, item.score, item.stale, meta, dict(item.provenance)))
            used_chars += len(text)
    return final_items

