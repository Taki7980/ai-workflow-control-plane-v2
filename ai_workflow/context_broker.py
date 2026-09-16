from __future__ import annotations
import ast, json, re, subprocess, shutil, concurrent.futures
from pathlib import Path
from .budget import ContextBudget, truncate
from .code_review_graph import (
    crg_environment,
    find_workspace_root,
    graph_exists,
    graph_freshness,
)
from .indexer import (
    index_data_dir,
    load_state,
    nested_repository_paths,
    row_fresh,
)
from .repository_registry import load_registry
from .workspace import registry_spec_to_root
from .memory import search_memory
from .models import ContextItem, RouteDecision, Lane
from .providers import ProviderStatus
from .math_retrieval import BM25Scorer, maximal_marginal_relevance, reciprocal_rank_fusion, tokenize
from .retrieval_policy import structural_requirements


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

def _git_changed_files(root: Path) -> list[str]:
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


def detect_changed_files(root: Path) -> list[str]:
    """Detect dirty files across the control root and all active nested repos."""
    root = Path(root).resolve()
    changed = list(_git_changed_files(root))
    seen = set(changed)
    for spec in load_registry(root):
        if not spec.included or spec.relative_path == ".":
            continue
        try:
            repository_root = registry_spec_to_root(root, spec)
        except (OSError, ValueError):
            continue
        for rel in _git_changed_files(repository_root):
            prefixed = f"{spec.relative_path.rstrip('/')}/{rel}"
            if prefixed not in seen:
                seen.add(prefixed)
                changed.append(prefixed)
    return changed

def _score(query: str, text: str) -> int:
    return len(set(tokenize(query)) & set(tokenize(text)))

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
            out.append(ContextItem(item.source, text, item.score, item.stale, meta))
            used += len(text)
    return out

def hot_cache(root: Path, query: str, limit: int) -> list[ContextItem]:
    rows = []
    workspace = find_workspace_root(root)
    for name in ["hot-cache.jsonl", "incident-cache.jsonl"]:
        for r in _jsonl(workspace / "ai-workspace" / "generated" / name):
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
    include_project_knowledge: bool = True,
) -> list[ContextItem]:
    state = load_state(root)
    generated = index_data_dir(root)
    workspace = find_workspace_root(root)
    out: list[ContextItem] = []
    for r in _jsonl(generated / "symbol-index.jsonl"):
        target = symbol or query
        s = 10 if symbol and r.get("symbol", "").lower() == symbol.lower() else _score(target, f"{r.get('symbol','')} {r.get('file','')}")
        if s:
            fresh = row_fresh(root, r, state)
            if fresh:
                out.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s), False, {"kind": "symbol"}))
    for r in _jsonl(generated / "endpoint-index.jsonl"):
        target = endpoint or query
        s = 10 if endpoint and endpoint.lower() in r.get("path", "").lower() else _score(target, f"{r.get('method','')} {r.get('path','')} {r.get('file','')}")
        if s and row_fresh(root, r, state):
            out.append(ContextItem("lightweight_index", json.dumps(r, separators=(",", ":")), float(s), False, {"kind": "endpoint"}))
    if include_project_knowledge:
        out.extend(_domain_hints(workspace, query, limit))
        out.extend(_research_hits(workspace, query, limit))
        for m in search_memory(
            workspace,
            query,
            limit=limit,
            minimum_confidence=min_conf,
            exclude_stale=True,
        ):
            compact = {
                k: m.get(k)
                for k in (
                    "id",
                    "type",
                    "summary",
                    "evidence",
                    "files",
                    "confidence",
                )
            }
            out.append(
                ContextItem(
                    "durable_memory",
                    json.dumps(
                        compact,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    float(m.get("score", 0)),
                    False,
                )
            )
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

def _run_crg(
    root: Path,
    args: list[str],
    timeout: int = 8,
) -> dict | None:
    if not shutil.which("code-review-graph"):
        return None
    workspace_root = find_workspace_root(root)
    if not graph_exists(workspace_root, root):
        return None
    freshness = graph_freshness(workspace_root, root)
    if not freshness.get("fresh"):
        return None
    try:
        proc = subprocess.run(
            ["code-review-graph", *args],
            cwd=root,
            env=crg_environment(workspace_root, root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return None
    return payload


def _verified_empty_crg(payload: dict) -> bool:
    confidence = str(payload.get("confidence") or "").casefold()
    return (
        "real absence" in confidence
        and "current" in confidence
        and "unverified" not in confidence
    )


def _crg_result_count(payload: dict, pattern: str) -> int:
    if pattern == "impact":
        raw = payload.get("total_impacted")
        if raw is None:
            raw = len(payload.get("impacted_nodes") or [])
    elif pattern == "architecture":
        raw = 1 if payload.get("summary") else 0
    else:
        raw = payload.get("result_count")
        if raw is None:
            raw = len(payload.get("results") or [])
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _compact_crg_payload(
    payload: dict,
    pattern: str,
    limit: int,
) -> dict:
    compact = {
        "status": "ok",
        "pattern": pattern,
    }
    for key in ("target", "summary", "confidence", "truncated"):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value

    if pattern == "impact":
        compact["total_impacted"] = _crg_result_count(payload, pattern)
        compact["impacted_files"] = list(
            payload.get("impacted_files") or []
        )[:limit]
        compact["impacted_nodes"] = list(
            payload.get("impacted_nodes") or []
        )[:limit]
        compact["edges"] = list(payload.get("edges") or [])[:limit]
    elif pattern == "architecture":
        for key in (
            "communities",
            "entry_points",
            "hub_nodes",
            "bridge_nodes",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                compact[key] = value[:limit]
    else:
        compact["result_count"] = _crg_result_count(payload, pattern)
        compact["results"] = list(payload.get("results") or [])[:limit]
        compact["edges"] = list(payload.get("edges") or [])[:limit]
    return compact


def _crg_item(
    payload: dict,
    pattern: str,
    score: float,
    limit: int,
    *,
    anchor: str | None = None,
) -> ContextItem:
    count = _crg_result_count(payload, pattern)
    empty_verified = count == 0 and _verified_empty_crg(payload)
    metadata = {
        "pattern": pattern,
        "structural_valid": count > 0 or empty_verified,
        "result_count": count,
        "empty_verified": empty_verified,
        "truncated": bool(payload.get("truncated", False)),
    }
    if anchor:
        metadata["anchor"] = anchor
    return ContextItem(
        "code_review_graph",
        json.dumps(
            _compact_crg_payload(payload, pattern, limit),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        score,
        False,
        metadata,
    )


def _crg_anchor(payload: dict | None) -> tuple[str | None, str | None]:
    if not payload:
        return None, None
    results = payload.get("results") or []
    if not isinstance(results, list):
        return None, None
    for row in results:
        if not isinstance(row, dict):
            continue
        anchor = str(
            row.get("qualified_name")
            or row.get("name")
            or ""
        ).strip()
        path = str(
            row.get("relative_path")
            or row.get("file_path")
            or row.get("path")
            or ""
        ).strip()
        if anchor:
            return anchor, path or None
    return None, None


def crg_context(
    root: Path,
    query: str,
    symbol: str | None,
    changed_files: list[str] | None,
    limit: int,
    *,
    patterns: tuple[str, ...] = (),
) -> list[ContextItem]:
    requested = patterns or structural_requirements(query)
    if not requested:
        if changed_files:
            requested = ("impact",)
        elif symbol:
            requested = ("callers_of",)
        else:
            requested = ("architecture",)

    results: list[ContextItem] = []
    anchor = symbol
    anchor_path: str | None = None

    needs_anchor = any(
        pattern in {"callers_of", "callees_of", "tests_for"}
        for pattern in requested
    ) or ("impact" in requested and not changed_files)
    if needs_anchor and not anchor:
        search = _run_crg(
            root,
            ["search", query, "--limit", str(limit)],
        )
        anchor, anchor_path = _crg_anchor(search)

    if "impact" in requested:
        impact_files = list(changed_files or [])
        if not impact_files and anchor_path:
            impact_files = [anchor_path]
        if not impact_files and anchor:
            search = _run_crg(
                root,
                ["search", anchor, "--limit", str(limit)],
            )
            _, anchor_path = _crg_anchor(search)
            if anchor_path:
                impact_files = [anchor_path]
        if impact_files:
            payload = _run_crg(
                root,
                ["impact", "--files", *impact_files],
            )
            if payload:
                results.append(
                    _crg_item(
                        payload,
                        "impact",
                        9.0,
                        limit,
                        anchor=anchor,
                    )
                )

    for pattern in requested:
        if pattern in {"impact", "architecture"}:
            continue
        if not anchor:
            continue
        payload = _run_crg(root, ["query", pattern, anchor])
        if payload:
            results.append(
                _crg_item(
                    payload,
                    pattern,
                    9.0,
                    limit,
                    anchor=anchor,
                )
            )
        if len(results) >= limit:
            return results[:limit]

    if "architecture" in requested and len(results) < limit:
        payload = _run_crg(root, ["architecture"])
        if payload:
            results.append(
                _crg_item(
                    payload,
                    "architecture",
                    8.0,
                    limit,
                )
            )

    return results[:limit]


def targeted_source(
    root: Path,
    query: str,
    limit: int,
) -> list[ContextItem]:
    terms = [x for x in re.split(r"\W+", query) if len(x) >= 4][:4]
    if not terms:
        return []
    pattern = "|".join(re.escape(term) for term in terms)
    nested = nested_repository_paths(root)

    if shutil.which("rg"):
        try:
            command = [
                "rg",
                "-n",
                "--no-heading",
                "-m",
                "2",
                "--glob",
                "!ai-workspace/**",
                "--glob",
                "!.ai/**",
                "--glob",
                "!**/.git/**",
                "--glob",
                "!**/node_modules/**",
            ]
            for relative in nested:
                command.extend(["--glob", f"!{relative}/**"])
            command.extend([pattern, "."])
            proc = subprocess.run(
                command,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=6,
                check=False,
            )
            lines = proc.stdout.splitlines()[:limit]
            return [
                ContextItem("targeted_source", line, 1.0)
                for line in lines
            ]
        except (OSError, subprocess.TimeoutExpired):
            pass

    out: list[ContextItem] = []
    excluded = {
        ".git",
        "node_modules",
        "dist",
        "build",
        "venv",
        ".venv",
        "__pycache__",
        "ai-workspace",
        ".ai",
    }

    def inside_nested(relative: str) -> bool:
        return any(
            relative == prefix
            or relative.startswith(prefix.rstrip("/") + "/")
            for prefix in nested
        )

    for path in root.rglob("*"):
        if len(out) >= limit:
            break
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        relative_text = relative.as_posix()
        if (
            any(part in excluded for part in relative.parts)
            or inside_nested(relative_text)
        ):
            continue
        try:
            if path.stat().st_size > 500_000:
                continue
            for line_number, line in enumerate(
                path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).splitlines(),
                1,
            ):
                if re.search(pattern, line, re.I):
                    out.append(
                        ContextItem(
                            "targeted_source",
                            f"{relative_text}:{line_number}: {line.strip()}",
                            1.0,
                        )
                    )
                    if len(out) >= limit:
                        break
        except OSError:
            continue
    return out


def gather(root: Path, query: str, decision: RouteDecision, budget: ContextBudget, config: dict, providers: ProviderStatus, symbol: str | None = None, endpoint: str | None = None, changed_files: list[str] | None = None) -> list[ContextItem]:
    limit = int(config["context"].get("max_results_per_source", 6))
    benchmark_isolation = bool(
        config["context"].get("benchmark_isolation", False)
    )
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
    # Priority 0: Hot cache. Research benchmarks isolate project-generated
    # knowledge so repository retrieval is not contaminated by prior runs.
    hot = [] if benchmark_isolation else hot_cache(root, query, limit)
    items += _cap_items(
        hot,
        budget.source_chars.get("hot_cache", 1000),
        seen_keys,
        query=query,
    )

    # Gather only potentially useful expensive providers in parallel.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_light = executor.submit(
            lightweight,
            root,
            query,
            symbol,
            endpoint,
            limit,
            float(config["memory"].get("minimum_confidence", 0.55)),
            not benchmark_isolation,
        )
        f_crg = executor.submit(crg_context, root, query, symbol, changed_files, limit) if wants_crg else None

        # Priority 1: Lightweight index + domain hints + research + memory
        remaining = max(0, budget.context_chars - sum(len(i.text) for i in items))
        light_budget = budget.source_chars.get("lightweight", 2000)
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
        has_code_evidence = any(
            item.source in code_sources and _score(query, item.text) > 0
            for item in items
        )
        has_structural_evidence = any(
            item.source == "code_review_graph"
            and bool(item.metadata.get("structural_valid"))
            for item in crg_items
        )
        needs_structural_fallback = (
            decision.structural_context and not has_structural_evidence
        )
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