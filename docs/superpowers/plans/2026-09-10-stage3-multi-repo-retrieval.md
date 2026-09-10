# Stage 3 Multi-Repo Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic multi-repository selection, globally conserved context budgeting, repository-scoped retrieval, provenance, and multi-repo benchmarks while first restoring the currently red retrieval benchmark baseline.

**Architecture:** Keep `ai-workspace/` centralized at the workspace root. Selection and budget math live in pure focused modules; repository execution/provenance live in `workspace_retrieval.py`. Existing `WorkflowEngine` remains the repository-local retrieval engine, but receives an explicit repository scope so central index rows can be filtered to one repository while semantic/CRG/source fallback execute inside that repository.

**Tech Stack:** Python 3.10–3.14 standard library, existing BM25/RRF/MMR helpers, existing `unittest` suite, Git/GitHub Actions. No new mandatory runtime dependency.

**Spec:** `docs/superpowers/specs/2026-09-10-stage3-multi-repo-retrieval-design.md`

## Global Constraints

- Python 3.10–3.14.
- Linux, Windows, and macOS must pass.
- Core stays offline-capable and dependency-light; no mandatory LLM/API dependency.
- `workspace_roots()` / Stage 2 registry remain the authority for allowed repositories.
- Never search or activate an unaccepted adjacent repository.
- Keep exactly one workspace state/config tree: `<workspace>/ai-workspace/`.
- Default `workspace.retrieval.max_selected_repositories = 3`.
- Default `workspace.retrieval.max_workers = 3`.
- Default `workspace.retrieval.deadline_seconds = 12`.
- In multi-repo mode the rank-1 repository receives at least 50% of the parent context budget.
- Sum of per-repo context and per-source budgets must never exceed the parent `ContextBudget`.
- Existing single-repo budget and output semantics stay backward compatible.
- Existing benchmark floors/baselines must not be weakened to make Stage 3 pass.
- No learned routing, bandits, dependency graph, topology learning, daemon, or retry loop in Stage 3.

## File Structure / Responsibility Map

- `ai_workflow/context_broker.py` — baseline lexical stopword repair and a narrow repository-scope hook for central indexes.
- `ai_workflow/workspace_selector.py` — immutable repository candidate/selection types and deterministic cheap repo scoring.
- `ai_workflow/workspace_budget.py` — immutable per-repo budget type and pure global budget allocator.
- `ai_workflow/workspace_retrieval.py` — candidate collection, repo-scoped execution, bounded concurrency, provenance, deterministic merge, orchestration diagnostics.
- `ai_workflow/workflow_engine.py` — remove the old full-budget-for-every-root loop; expose a single-repository engine seam with central index scope.
- `ai_workflow/adaptive_broker.py` — preserve public `gather_detailed*` compatibility and add repo-scoped wrapper plumbing only.
- `ai_workflow/config.py` — defaults + validation for `workspace.retrieval`.
- `ai_workflow/cli.py` — route `brief` / `context` through workspace orchestration.
- `ai_workflow/benchmark.py` — surface multi-repo retrieval metrics from orchestration metadata.
- `.github/workflows/tests.yml` — include Stage 3 modules in focused Ruff/Mypy gates.
- `tests/test_context_broker.py` — red-main regression and exact-match protection.
- `tests/test_workspace_selector.py` — selection behavior and determinism.
- `tests/test_workspace_budget.py` — budget conservation and rounding.
- `tests/test_workspace_retrieval.py` — provenance, concurrency, deadline, repo-scoped execution.
- `tests/test_cli.py` or existing CLI test module — additive orchestration output compatibility.
- `tests/test_benchmark.py` / existing benchmark tests — RepoRecall/WrongRepo/budget metrics.
- `docs/multi-repo-workspace-registry.md` — Stage 3 behavior and operational model.

---

### Task 0: Restore the merged benchmark baseline

**Files:**
- Modify: `ai_workflow/context_broker.py`
- Modify: `tests/test_context_broker.py`
- Verify: `benchmarks/sample-tasks.json`, `benchmarks/baseline.json`, `scripts/check_benchmark_regression.py`

**Interfaces:**
- Consumes: existing `tokenize(text: str) -> list[str]` and `lightweight(...)`.
- Produces: `_semantic_overlap_score(query: str, text: str) -> int`; exact symbol/endpoint branches remain unchanged.

- [ ] **Step 1: Lock the real CRG displacement regression test**

Keep the merged test but make the expected behavior explicit: low-information grammatical matches (`for`, `be`, `the`, `where`, `whether`, etc.) must not push `crg_gate` out of the lightweight shortlist.

```python
def test_lightweight_keeps_rare_query_signal_under_stopword_heavy_noise(self):
    noisy = [
        {"symbol": "repository_mutation_waits_for_lock", "file": "tests/test_repository_registry.py"},
        {"symbol": "repository_rules_for_worktrees", "file": "tests/test_repository_registry.py"},
        {"symbol": "should_be_repository_safe", "file": "tests/test_repository_registry.py"},
        {"symbol": "repository_refresh_for_branch", "file": "tests/test_repository_registry.py"},
        {"symbol": "where_repository_is_loaded", "file": "tests/test_repository_registry.py"},
        {"symbol": "whether_repository_is_dirty", "file": "tests/test_repository_registry.py"},
    ]
    rare = {"symbol": "crg_gate", "file": "ai_workflow/retrieval_policy.py"}
    # Existing patches for load_state/_jsonl/row_fresh/domain/research/memory stay in place.
    items = lightweight(
        Path(td),
        "Where do we decide whether CRG should be attempted for a large repository?",
        None,
        None,
        limit=6,
        min_conf=0.5,
    )
    self.assertTrue(any('"symbol":"crg_gate"' in item.text for item in items))
```

- [ ] **Step 2: Add an exact-match protection test**

```python
def test_lightweight_exact_symbol_match_keeps_score_ten(self):
    row = {"symbol": "ProcessPayment", "file": "payments.py"}
    # Patch index/state helpers as in neighboring tests.
    items = lightweight(Path(td), "irrelevant words", "ProcessPayment", None, 5, 0.5)
    self.assertEqual(items[0].score, 10.0)
```

- [ ] **Step 3: Run the focused tests and confirm the stopword case is red before implementation**

Run:

```bash
python -m unittest tests.test_context_broker.ContextBrokerTests.test_lightweight_keeps_rare_query_signal_under_stopword_heavy_noise -v
python -m unittest tests.test_context_broker.ContextBrokerTests.test_lightweight_exact_symbol_match_keeps_score_ten -v
```

Expected: stopword test FAIL; exact symbol test PASS.

- [ ] **Step 4: Implement a generic semantic-overlap scorer without changing exact branches**

Add a frozen stopword set and helper near `_score`:

```python
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
```

Use `_semantic_overlap_score(...)` only in the generic symbol/endpoint lexical branches inside `lightweight()`. Keep `_score()` unchanged for existing cache/research behavior and keep explicit symbol/endpoint score-10 branches untouched.

- [ ] **Step 5: Run focused tests and the exact CI benchmark command**

```bash
python -m unittest tests.test_context_broker -v
python -m ai_workflow index
python -m ai_workflow doctor --strict
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json > /dev/null
python scripts/check_benchmark_regression.py benchmarks/baseline.json benchmark-result.json
```

Expected: all PASS; benchmark gate restored without editing `benchmarks/baseline.json`.

- [ ] **Step 6: Commit the baseline repair independently**

```bash
git add ai_workflow/context_broker.py tests/test_context_broker.py
git commit -m "fix: restore semantic retrieval benchmark"
```

---

### Task 1: Add Stage 3 configuration and repository candidate contracts

**Files:**
- Create: `ai_workflow/workspace_selector.py`
- Modify: `ai_workflow/config.py`
- Test: `tests/test_workspace_selector.py`
- Test: existing config validation test module

**Interfaces:**
- Consumes: `workspace_roots(root, config)`, `aggregate_workspace_fingerprint(...)`, `repository_id(...)`, `detect_changed_files(...)`.
- Produces:

```python
@dataclass(frozen=True)
class RepositoryCandidate:
    root: Path
    repository_id: str
    repository_path: str
    remote_identity: str | None
    fingerprint: str
    changed_files: tuple[str, ...]
    is_primary: bool


@dataclass(frozen=True)
class RepositorySelection:
    candidate: RepositoryCandidate
    score: float
    rank: int
    selected: bool
    reasons: tuple[str, ...]


def build_repository_candidates(
    workspace_root: Path,
    config: dict,
    explicit_changed_files: list[str] | None = None,
) -> list[RepositoryCandidate]: ...
```

- [ ] **Step 1: Add config-default tests**

Assert `default_config()["workspace"]["retrieval"]` equals:

```python
{
    "max_selected_repositories": 3,
    "max_workers": 3,
    "deadline_seconds": 12,
}
```

Add validation cases rejecting `0`, negative values, booleans, and non-numeric deadline values.

- [ ] **Step 2: Run config tests red**

```bash
python -m unittest discover -s tests -p "test_config*.py" -v
```

Expected: new retrieval-setting tests FAIL.

- [ ] **Step 3: Add defaults and strict validation in `config.py`**

Extend `_DEFAULT_CONFIG["workspace"]`:

```python
"retrieval": {
    "max_selected_repositories": 3,
    "max_workers": 3,
    "deadline_seconds": 12,
},
```

Validate:

```python
retrieval = data["workspace"].get("retrieval", {
    "max_selected_repositories": 3,
    "max_workers": 3,
    "deadline_seconds": 12,
})
if not isinstance(retrieval, dict):
    raise ValueError("workspace.retrieval must be an object")
_positive_int(retrieval.get("max_selected_repositories", 3), "workspace.retrieval.max_selected_repositories")
_positive_int(retrieval.get("max_workers", 3), "workspace.retrieval.max_workers")
deadline = retrieval.get("deadline_seconds", 12)
if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or float(deadline) <= 0:
    raise ValueError("workspace.retrieval.deadline_seconds must be a positive number")
```

- [ ] **Step 4: Write candidate-construction tests**

Cover:
- primary root is represented once;
- included child repos become candidates;
- excluded repos never appear;
- duplicate folder names remain distinct by repository ID;
- explicit changed files are partitioned to the owning repo by longest repository-prefix match;
- unprefixed explicit changed files remain assigned to the primary repository for CLI backward compatibility;
- auto-detected Git changes are per repo when no explicit list is supplied;
- absolute checkout paths do not become portable repository identity.

- [ ] **Step 5: Implement candidate construction**

Use `workspace_roots()` as the only candidate source. Derive stable `repository_path` from Stage 2 registry/fingerprint logic. For explicit workspace-relative changed paths such as `backend/internal/payments.go`, assign `internal/payments.go` to candidate `backend`; do not pass the workspace prefix into repo-local Git/retrieval calls.

- [ ] **Step 6: Run focused tests**

```bash
python -m unittest tests.test_workspace_selector -v
python -m unittest discover -s tests -p "test_config*.py" -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ai_workflow/config.py ai_workflow/workspace_selector.py tests/test_workspace_selector.py tests/test_config*.py
git commit -m "feat: add multi-repo candidate contracts"
```

---

### Task 2: Implement deterministic repository preselection

**Files:**
- Modify: `ai_workflow/workspace_selector.py`
- Test: `tests/test_workspace_selector.py`

**Interfaces:**
- Consumes: `RepositoryCandidate`.
- Produces:

```python
def select_repositories(
    workspace_root: Path,
    candidates: list[RepositoryCandidate],
    query: str,
    *,
    symbol: str | None = None,
    endpoint: str | None = None,
    max_selected: int = 3,
    max_index_candidates: int = 200,
) -> list[RepositorySelection]: ...
```

Signal ordering must remain: explicit hint > changed-file > identity/path/name > indexed symbol/file path > weak primary prior.

- [ ] **Step 1: Write deterministic selection tests first**

Include these concrete behaviors:

```python
def test_clear_secondary_match_outranks_primary(): ...
def test_unrelated_repository_is_skipped(): ...
def test_primary_prior_only_breaks_ambiguous_tie(): ...
def test_symbol_hint_selects_repo_containing_symbol(): ...
def test_endpoint_hint_selects_repo_containing_endpoint(): ...
def test_changed_file_lifts_owning_repository(): ...
def test_input_permutation_does_not_change_rank_order(): ...
def test_duplicate_folder_names_are_distinct_by_repository_id(): ...
def test_no_more_than_three_repositories_selected_by_default(): ...
```

- [ ] **Step 2: Run selector tests red**

```bash
python -m unittest tests.test_workspace_selector -v
```

Expected: selection tests FAIL because `select_repositories` does not exist.

- [ ] **Step 3: Implement bounded index-signal extraction**

Do not scan repository source files. Read only central generated indexes under:

```text
<workspace>/ai-workspace/generated/symbol-index.jsonl
<workspace>/ai-workspace/generated/endpoint-index.jsonl
```

Filter rows by repository prefix. For the primary repository `.` accept unprefixed rows only; for child repository `backend`, accept rows whose indexed `file` starts with `backend/`, then strip that prefix when comparing repo-local hints.

Read at most `context.selector.max_selector_candidates` rows per candidate per index signal pass. Missing/stale index contributes no index score and never triggers adjacent-folder scanning.

- [ ] **Step 4: Implement explicit deterministic signal weights**

Use fixed weights to encode the approved priority while keeping the constants private to the module:

```python
_EXPLICIT_HINT_WEIGHT = 100.0
_CHANGED_FILE_WEIGHT = 40.0
_IDENTITY_WEIGHT = 12.0
_INDEX_WEIGHT = 3.0
_PRIMARY_PRIOR = 0.25
```

Score only meaningful query tokens (reuse `tokenize` and the same low-information token filter introduced in Task 0). Append reason codes such as:

```text
symbol_hint
endpoint_hint
changed_file
identity_match
index_match
primary_prior
```

Repositories with only the primary prior and no query evidence may remain eligible only when no candidate has stronger evidence; once a positive-evidence repository exists, pure-prior unrelated repositories are skipped.

- [ ] **Step 5: Sort and select deterministically**

Sort by:

```python
(-selection_score, candidate.repository_id, candidate.repository_path.casefold())
```

Assign rank after sorting. Mark only the first `max_selected` positive/eligible entries selected; return skipped entries too or expose a companion `selection_report()` helper so diagnostics can state why each repo was skipped.

- [ ] **Step 6: Run selector tests repeatedly under shuffled input**

```bash
python -m unittest tests.test_workspace_selector -v
```

Expected: PASS across repeated randomized fixture orders.

- [ ] **Step 7: Commit**

```bash
git add ai_workflow/workspace_selector.py tests/test_workspace_selector.py
git commit -m "feat: add deterministic repository selection"
```

---

### Task 3: Add one globally conserved per-repository budget allocator

**Files:**
- Create: `ai_workflow/workspace_budget.py`
- Test: `tests/test_workspace_budget.py`

**Interfaces:**
- Consumes: `ContextBudget`, selected `RepositorySelection` objects.
- Produces:

```python
@dataclass(frozen=True)
class RepositoryBudget:
    repository_id: str
    rank: int
    ratio: float
    context: ContextBudget


def allocate_repository_budgets(
    parent: ContextBudget,
    selections: list[RepositorySelection],
) -> list[RepositoryBudget]: ...
```

- [ ] **Step 1: Write budget tests first**

Required tests:

```python
def test_single_repo_gets_exact_parent_budget(): ...
def test_multi_repo_rank_one_gets_at_least_half(): ...
def test_context_chars_are_globally_conserved(): ...
def test_each_source_budget_is_globally_conserved(): ...
def test_zero_score_repo_receives_no_allocation(): ...
def test_rounding_is_deterministic(): ...
def test_ten_repo_fixture_cannot_multiply_budget(): ...
def test_allocation_is_input_order_independent(): ...
```

- [ ] **Step 2: Run tests red**

```bash
python -m unittest tests.test_workspace_budget -v
```

- [ ] **Step 3: Implement deterministic ratio allocation**

For one selected repository, reuse the exact parent object values.

For multiple repos:
1. normalize positive selector scores;
2. compute proportional shares;
3. if rank-1 share is below `0.5`, set it to `0.5` and renormalize the remaining repositories into `0.5`;
4. allocate integer `context_chars` by floor;
5. distribute remainder one char at a time in stable rank/repository-ID order;
6. repeat the same integer-allocation function for every key in `parent.source_chars`;
7. derive `estimated_tokens` from the context-char ratio while ensuring total estimated tokens never exceeds parent; preserve `output_tokens` unchanged only for orchestration metadata, not multiplied per repo.

Use a shared private helper:

```python
def _allocate_integers(total: int, weighted: list[tuple[str, float]]) -> dict[str, int]: ...
```

- [ ] **Step 4: Add invariant assertions inside tests, not runtime-only assumptions**

```python
self.assertLessEqual(sum(b.context.context_chars for b in budgets), parent.context_chars)
for source, parent_chars in parent.source_chars.items():
    self.assertLessEqual(sum(b.context.source_chars[source] for b in budgets), parent_chars)
```

- [ ] **Step 5: Run focused tests**

```bash
python -m unittest tests.test_workspace_budget -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai_workflow/workspace_budget.py tests/test_workspace_budget.py
git commit -m "feat: conserve context budget across repositories"
```

---

### Task 4: Add repository-scoped central-index retrieval

**Files:**
- Modify: `ai_workflow/context_broker.py`
- Modify: `ai_workflow/workflow_engine.py`
- Modify: `ai_workflow/adaptive_broker.py`
- Test: `tests/test_context_broker.py`
- Test: existing workflow-engine/adaptive-broker test modules

**Interfaces:**
- Consumes: central workspace index + repository content root.
- Produces a narrow scope contract:

```python
@dataclass(frozen=True)
class RepositoryScope:
    workspace_root: Path
    repository_root: Path
    repository_path: str
```

Preferred location: `ai_workflow/workspace_selector.py` if that keeps identity types together; otherwise define it privately in `context_broker.py` only if no other module needs it.

Extend repository-local broker entry points with keyword-only scope:

```python
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
) -> list[ContextItem]: ...
```

`root` remains the repository execution root. `workspace_root` defaults to `root`, preserving every existing caller.

- [ ] **Step 1: Write scoped-index tests**

Create a temp workspace with central index rows:

```text
backend/payments.py -> ProcessPayment
frontend/payment.ts -> PaymentForm
```

Assert a backend-scoped lightweight/gather call returns `ProcessPayment` and never returns `PaymentForm`; frontend scope must do the inverse.

Also assert `targeted_source`, Git changed-file resolution, semantic provider root, and CRG root remain the actual repository root rather than the workspace root.

- [ ] **Step 2: Run focused tests red**

```bash
python -m unittest tests.test_context_broker -v
python -m unittest discover -s tests -p "test_*workflow*engine*.py" -v
```

- [ ] **Step 3: Separate index-state root from repository content root**

Inside `lightweight()` and helpers that read generated symbol/endpoint/index-state files:

```python
index_root = workspace_root or root
```

Filter central rows with a helper:

```python
def _row_for_repository(row: dict, repository_path: str) -> dict | None:
    file = str(row.get("file", ""))
    if repository_path == ".":
        if "/" in file and file.split("/", 1)[0] in known_child_prefixes:
            return None
        return row
    prefix = repository_path.rstrip("/") + "/"
    if not file.startswith(prefix):
        return None
    scoped = dict(row)
    scoped["file"] = file[len(prefix):]
    return scoped
```

Do not infer child prefixes from arbitrary directories. Pass the accepted repo prefixes from orchestration when primary filtering needs them, or use exact selected repository path filtering supplied by Stage 2 candidate metadata.

Freshness checks use `repository_root / scoped_file` but compare against the central state row keyed by the original workspace-relative file path. Add a focused helper instead of changing `indexer.row_fresh()` globally.

- [ ] **Step 4: Make `WorkflowEngine` repository-local**

Remove the existing internal loop that calls `base_gather` once for every `workspace_roots(root, config)` using the full parent budget. A single `WorkflowEngine.gather_detailed_async()` invocation must retrieve for exactly one repository root/budget.

Add keyword-only parameters:

```python
workspace_root: Path | None = None,
repository_path: str = ".",
```

and pass them into `base_gather` through a compatible wrapper/partial. Existing public calls omit them and retain single-root behavior.

Set `workspace_state` to the repository-local fingerprint when repo-scoped; workspace aggregate state is added later by workspace orchestration.

- [ ] **Step 5: Preserve public adaptive-broker compatibility**

Add the same optional keyword-only scope arguments to `gather_detailed_async()` / `gather_detailed()` and forward them to `WorkflowEngine`. Do not change positional argument order.

- [ ] **Step 6: Run all retrieval engine tests**

```bash
python -m unittest tests.test_context_broker -v
python -m unittest discover -s tests -p "test_*broker*.py" -v
python -m unittest discover -s tests -p "test_*workflow*.py" -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ai_workflow/context_broker.py ai_workflow/workflow_engine.py ai_workflow/adaptive_broker.py tests
git commit -m "refactor: support repository-scoped retrieval"
```

---

### Task 5: Orchestrate selected repositories with bounded concurrency and provenance

**Files:**
- Create: `ai_workflow/workspace_retrieval.py`
- Modify: `ai_workflow/models.py` only if dedupe needs a repository-aware helper; otherwise keep `ContextItem` unchanged and use orchestration-local keys.
- Test: `tests/test_workspace_retrieval.py`

**Interfaces:**
- Consumes: `build_repository_candidates`, `select_repositories`, `allocate_repository_budgets`, `adaptive_broker.gather_detailed_async`.
- Produces:

```python
@dataclass(frozen=True)
class WorkspaceRetrievalResult:
    items: tuple[ContextItem, ...]
    diagnostics: dict[str, Any]


async def gather_workspace_detailed_async(
    workspace_root: Path,
    query: str,
    decision: RouteDecision,
    budget: ContextBudget,
    config: dict,
    providers: ProviderStatus,
    symbol: str | None = None,
    endpoint: str | None = None,
    changed_files: list[str] | None = None,
    *,
    write_telemetry: bool = False,
) -> WorkspaceRetrievalResult: ...


def gather_workspace_detailed(...same args...) -> WorkspaceRetrievalResult: ...
```

- [ ] **Step 1: Write orchestration tests first**

Cover:

```python
def test_only_selected_repositories_are_called(): ...
def test_each_repo_receives_only_its_budget_slice(): ...
def test_changed_files_are_repo_local(): ...
def test_every_item_has_repository_provenance(): ...
def test_identical_text_from_two_repos_keeps_both_provenances(): ...
def test_completion_order_does_not_change_final_order(): ...
def test_repo_timeout_preserves_other_repo_results(): ...
def test_global_deadline_bounds_total_operation(): ...
def test_single_repo_path_matches_existing_behavior(): ...
```

Mock repo retrieval for concurrency/deadline tests; use real temp Git repos only for provenance/fingerprint integration tests.

- [ ] **Step 2: Run orchestration tests red**

```bash
python -m unittest tests.test_workspace_retrieval -v
```

- [ ] **Step 3: Implement repository provenance attachment**

For every item, copy metadata/provenance and add portable fields:

```python
metadata.update({
    "repository_id": selection.candidate.repository_id,
    "repository_path": selection.candidate.repository_path,
    "repository_fingerprint": selection.candidate.fingerprint,
})
provenance.update({
    "repository_id": selection.candidate.repository_id,
    "repository_path": selection.candidate.repository_path,
    "repository_fingerprint": selection.candidate.fingerprint,
})
```

Never serialize the repository absolute root into portable item metadata.

Repository-aware dedupe key for cross-repo merge:

```python
(repo_id, item.dedupe_key)
```

This intentionally keeps identical text from different repositories as distinct evidence.

- [ ] **Step 4: Implement bounded concurrency under one monotonic deadline**

Use standard-library `asyncio` only:

```python
max_workers = min(
    int(config["workspace"]["retrieval"].get("max_workers", 3)),
    len(selected),
)
deadline_seconds = float(config["workspace"]["retrieval"].get("deadline_seconds", 12))
```

Guard concurrency with `asyncio.Semaphore(max_workers)`. Compute one `deadline_at = time.monotonic() + deadline_seconds`; each repo receives only `max(0.001, deadline_at - time.monotonic())` via `asyncio.wait_for(...)`.

Do not retry timed-out repos and do not expand to skipped repos.

- [ ] **Step 5: Implement deterministic cross-repo merge**

Before final hard cap, normalize repository-local position so local relevance remains primary:

```python
rank_key = (
    local_rank,
    -selection.score,
    -changed_file_boost,
    candidate.repository_id,
    item.source,
    normalized_source_path,
    item.dedupe_key,
)
```

`local_rank` comes from the order returned by repository-local retrieval. `changed_file_boost` is `1` only when the item provenance/path maps to that repo's changed-file set, otherwise `0`.

Sort results by `rank_key`; then consume at most `parent.context_chars`. Truncation must copy metadata and mark `truncated=True` exactly as existing hard caps do.

- [ ] **Step 6: Build orchestration diagnostics**

Return additive fields:

```python
{
    "workspace_fingerprint": aggregate["fingerprint"],
    "selected_repositories": [...],
    "skipped_repositories": [...],
    "repositories_searched": N,
    "repository_results": {
        repo_id: {
            "status": "ok" | "timeout" | "error",
            "selector_score": float,
            "selector_reasons": [...],
            "changed_files": [...],
            "allocated_context_chars": int,
            "used_context_chars": int,
            "source_chars": {...},
        }
    },
    "budget": {
        "parent_context_chars": parent.context_chars,
        "allocated_context_chars": total_allocated,
        "used_context_chars": total_used,
    },
    "scheduler": {
        "max_workers": effective_workers,
        "deadline_seconds": deadline_seconds,
        "deadline_exceeded": bool,
    },
}
```

- [ ] **Step 7: Run orchestration tests**

```bash
python -m unittest tests.test_workspace_retrieval -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add ai_workflow/workspace_retrieval.py ai_workflow/models.py tests/test_workspace_retrieval.py
git commit -m "feat: orchestrate bounded multi-repo retrieval"
```

---

### Task 6: Integrate workspace retrieval into CLI without breaking single-repo output

**Files:**
- Modify: `ai_workflow/cli.py`
- Test: existing CLI test module

**Interfaces:**
- Consumes: `gather_workspace_detailed(...)`.
- Produces: additive `retrieval["workspace_orchestration"]` metadata for `brief` and `context`.

- [ ] **Step 1: Add CLI compatibility tests**

Test both one-repo and multi-repo temp workspaces.

Single repo assertions:
- existing keys still exist (`lane`, `risk`, `budget`, `retrieval`, `context`, `changed_files_detected`);
- context remains bounded;
- orchestration metadata is additive.

Multi-repo assertions:
- selected repo IDs/paths appear;
- skipped repo reasons appear;
- aggregate workspace fingerprint appears;
- `repositories_searched` matches actual calls;
- total allocation/usage never exceeds parent budget.

- [ ] **Step 2: Run CLI tests red**

```bash
python -m unittest discover -s tests -p "test_cli*.py" -v
```

- [ ] **Step 3: Replace direct `gather_detailed` calls in `cmd_brief` and `cmd_context`**

Use:

```python
workspace_result = gather_workspace_detailed(
    root,
    args.task,
    decision,
    budget,
    config,
    providers,
    args.symbol,
    args.endpoint,
    changed,
    write_telemetry=(decision.lane.value != "answer" or args.trace),
)
items = list(workspace_result.items)
retrieval = dict(workspace_result.diagnostics.get("primary_retrieval", {}))
retrieval["workspace_orchestration"] = workspace_result.diagnostics
```

The exact shape may use a top-level merged diagnostics object instead; preserve all existing retrieval keys consumed by `_format_brief`, benchmark code, and orchestration contract tests.

- [ ] **Step 4: Update human-readable brief formatting minimally**

Add compact lines only when orchestration contains multiple candidates/repositories:

```text
[REPOSITORIES] backend, frontend
[REPO_BUDGET] allocated=... used=...
```

Do not dump absolute local paths.

- [ ] **Step 5: Run CLI and broker regression tests**

```bash
python -m unittest discover -s tests -p "test_cli*.py" -v
python -m unittest discover -s tests -p "test_*broker*.py" -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ai_workflow/cli.py tests
git commit -m "feat: expose multi-repo retrieval in cli"
```

---

### Task 7: Add multi-repo benchmark metrics and adversarial fixtures

**Files:**
- Modify: `ai_workflow/benchmark.py`
- Add/modify: benchmark test data under `benchmarks/` only if deterministic portable fixtures are appropriate; otherwise construct temp fixtures in tests.
- Test: existing benchmark test module plus `tests/test_workspace_retrieval.py` / `tests/test_workspace_selector.py`.

**Interfaces:**
- Consumes: orchestration diagnostics with selected repositories and item provenance.
- Produces benchmark row/summary fields:

```text
repo_recall_at_k
wrong_repo_rate
file_recall_at_k
repositories_searched
allocated_context_chars
used_context_chars
budget_conserved
```

- [ ] **Step 1: Extend benchmark task schema additively**

Support optional case fields:

```json
{
  "expected_repositories": ["backend"],
  "forbidden_repositories": ["frontend"],
  "relevant_files": ["internal/payment/service.go"]
}
```

Existing benchmark files without these fields must behave exactly as before.

- [ ] **Step 2: Write metric unit tests**

Define pure helpers:

```python
def repository_metrics(items: list[ContextItem], expected: list[str], forbidden: list[str], k: int = 5) -> dict | None: ...
def file_recall(items: list[ContextItem], relevant_files: list[str], k: int = 5) -> float | None: ...
```

Assert repository identity comes from `item.metadata["repository_path"]` / provenance, never filename basename guessing.

- [ ] **Step 3: Add a 10-repository adversarial integration fixture**

Create ten temporary Git repos under one workspace, register/include them explicitly, give only one repo symbols/files matching the task, and assert:
- selector chooses the correct repo;
- unrelated repos are not searched;
- `RepoRecall@K == 1.0` for the gold repo;
- `WrongRepoRate == 0.0` for forbidden repos;
- total repo allocations do not exceed parent budget.

Add a same-basename fixture where two repositories are both named `api` in different stable legacy/registry identities and ensure provenance/metrics do not collide.

- [ ] **Step 4: Integrate metrics into `run_benchmark`**

For each case, read `workspace_orchestration` and context provenance. Keep the existing summary unchanged except for additive Stage 3 fields. Add summary means only when corresponding case data exists.

- [ ] **Step 5: Run benchmark tests and the original benchmark regression gate**

```bash
python -m unittest discover -s tests -p "test_benchmark*.py" -v
python -m ai_workflow index
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json > /dev/null
python scripts/check_benchmark_regression.py benchmarks/baseline.json benchmark-result.json
```

Expected: PASS; original floors unchanged.

- [ ] **Step 6: Commit**

```bash
git add ai_workflow/benchmark.py benchmarks tests
git commit -m "test: add multi-repo retrieval metrics"
```

---

### Task 8: Harden quality gates, docs, and final verification

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `docs/multi-repo-workspace-registry.md`
- Modify: README only if current setup/brief documentation needs one concise Stage 3 note.

**Interfaces:**
- Consumes: all Stage 3 modules.
- Produces: CI enforcement and user-facing behavior documentation.

- [ ] **Step 1: Add Stage 3 modules to Ruff/Mypy focused gates**

Add:

```text
ai_workflow/workspace_selector.py
ai_workflow/workspace_budget.py
ai_workflow/workspace_retrieval.py
```

Also add any existing modified typed-boundary file (`workflow_engine.py` or `context_broker.py`) if it is clean under the focused rules. Do not remove existing quality targets.

- [ ] **Step 2: Document Stage 3 operational behavior**

Update `docs/multi-repo-workspace-registry.md` with:
- accepted repos are candidates, not automatically searched;
- selector chooses up to 3 by default;
- one parent budget is shared;
- `brief` shows selected/skipped repos and allocation;
- repo-local changed files and provenance;
- one 12-second global deadline / max 3 workers by default;
- no dependency graph or learned routing yet.

- [ ] **Step 3: Run full local verification commands**

```bash
python -m unittest discover -s tests -v
python -m compileall -q ai_workflow
ruff check --select E,F,UP,BLE,EXE ai_workflow/workspace_selector.py ai_workflow/workspace_budget.py ai_workflow/workspace_retrieval.py ai_workflow/context_broker.py ai_workflow/workflow_engine.py
mypy --follow-imports=skip ai_workflow/workspace_selector.py ai_workflow/workspace_budget.py ai_workflow/workspace_retrieval.py
python -m ai_workflow index
python -m ai_workflow doctor --strict
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json --output benchmark-result.json > /dev/null
python scripts/check_benchmark_regression.py benchmarks/baseline.json benchmark-result.json
```

Expected: all PASS.

- [ ] **Step 4: Commit docs/quality gate changes**

```bash
git add .github/workflows/tests.yml docs README.md
git commit -m "docs: finalize stage3 multi-repo retrieval"
```

- [ ] **Step 5: Push/open PR and verify the exact final head**

Create a PR from `research/stage3-multi-repo-retrieval` to `main`. Confirm the final head SHA, then require successful GitHub Actions jobs for:

```text
compatibility: Ubuntu Python 3.10
compatibility: Ubuntu Python 3.11
compatibility: Ubuntu Python 3.12
compatibility: Ubuntu Python 3.13
compatibility: Ubuntu Python 3.14
compatibility: Windows Python 3.14
compatibility: macOS Python 3.14
quality
package-smoke
benchmark-regression
```

- [ ] **Step 6: Review PR threads and final diff**

Check every inline review finding against source, not merely thread resolution state. Any valid correctness/security issue gets a regression test and fix before final verification.

- [ ] **Step 7: Run verification-before-completion gate**

Refetch PR metadata and CI for the exact final head. Stage 3 is ready only if every required job is successful, PR is mergeable, and no verified unresolved correctness/security finding remains. Do not merge unless the user explicitly authorizes it.

---

## Plan Self-Review

### Spec coverage

- Baseline benchmark repair: Task 0.
- Accepted repository candidate authority: Task 1.
- Deterministic preselection: Task 2.
- Global budget conservation / 50% top floor: Task 3.
- Central index + repo-local execution compatibility: Task 4.
- Provenance / concurrency / deadline / deterministic merge: Task 5.
- CLI additive output: Task 6.
- RepoRecall/WrongRepo/FileRecall/10-repo fixtures: Task 7.
- Cross-platform quality/docs/final CI: Task 8.
- Deferred Stage 4+ work is absent from the plan.

### Type consistency

- `RepositoryCandidate` and `RepositorySelection` are defined in Task 1/2 and consumed by Task 3/5.
- `RepositoryBudget` is defined in Task 3 and consumed by Task 5.
- `workspace_root` + `repository_path` are keyword-only compatibility additions in Task 4 and consumed by Task 5.
- `WorkspaceRetrievalResult` is defined in Task 5 and consumed by Task 6/7.

### Scope check

The plan remains one subsystem: deterministic multi-repository retrieval orchestration. It does not add the Stage 4 dependency graph, learned routing, daemon behavior, or new provider trust capabilities.
