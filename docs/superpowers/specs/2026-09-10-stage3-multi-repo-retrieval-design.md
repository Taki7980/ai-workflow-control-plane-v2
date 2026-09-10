# Stage 3 Design: Multi-Repo Retrieval Orchestration

Date: 2026-09-10
Branch: `research/stage3-multi-repo-retrieval`
Base: `main` at `7ee86f63f7a4759020b6ca497974d45caf66555e`

## Goal

Make multi-repository retrieval real rather than merely multi-root aware. A task should search only the accepted repositories that are relevant, split one global context budget across them, retrieve independently per repository, and merge evidence deterministically with preserved repository provenance.

Stage 3 must keep the control plane offline-capable, deterministic, dependency-light, and backward compatible for single-repository workspaces.

## Blocking baseline repair

Current `main` is red because the semantic retrieval benchmark regressed after PR #19 merged. Before Stage 3 feature work, repair that baseline on the Stage 3 branch and verify the full existing CI matrix.

Known root cause: lightweight lexical scoring allows grammatical stopwords such as `for` and `be` to inflate irrelevant symbol matches and displace a CRG-specific candidate. The repair must:

- preserve exact symbol/endpoint matching behavior;
- filter only low-information grammatical tokens from generic lexical overlap;
- keep the real CRG displacement regression test;
- not lower benchmark thresholds or alter benchmark baselines;
- restore the full pre-Stage-3 CI baseline before orchestration code is added.

## Scope

Stage 3 includes:

- deterministic repository preselection;
- one globally conserved retrieval/context budget;
- per-repository changed-file detection and retrieval;
- repository-aware provenance on every retrieved item;
- deterministic cross-repository merge/packing;
- bounded multi-repository concurrency under one global deadline;
- brief/context orchestration metadata;
- wrong-repository and budget-conservation benchmarks/tests.

Stage 3 explicitly excludes:

- learned/adaptive repository routing;
- contextual bandits;
- topology learning;
- cross-repository dependency/intelligence graph;
- daemon/background services;
- provider-driven repository activation;
- arbitrary adjacent-folder discovery beyond the accepted Stage 2 registry.

## Architecture

### 1. Repository candidates

`workspace_roots()` remains the authority for which repositories are allowed to participate. Stage 3 must never search a repository that is not already active/accepted through the Stage 2 workspace contract.

Each candidate repository is represented by a small immutable descriptor containing:

- absolute local root for execution only;
- stable repository ID;
- workspace-relative path or stable legacy identity;
- canonical remote identity when available;
- repository fingerprint;
- detected changed files;
- lightweight lexical/index signals used for selection.

Absolute paths must never affect ranking identity or aggregate fingerprints.

### 2. Cheap repository selector

Add `ai_workflow/workspace_selector.py`.

The selector runs before expensive retrieval. It is deterministic and model-free. It scores active repositories using only cheap signals:

- repository name/path/remote identity tokens;
- task tokens;
- indexed file paths and symbol names;
- explicit or auto-detected changed files;
- a small primary-repository prior;
- optional explicit symbol/endpoint hints.

The primary repository receives a modest prior so ambiguous local tasks still behave naturally, but it must not automatically outrank a clearly matching secondary repository.

Selection output includes a reason breakdown so `brief`/telemetry can explain why a repository was selected or skipped.

Unrelated repositories should normally receive score zero and no retrieval budget.

### 3. One global budget

Add `ai_workflow/workspace_budget.py`.

The lane-level `ContextBudget` remains the hard parent ceiling. Stage 3 allocates slices to selected repositories; it never creates one full budget per repository.

Required invariant:

`sum(repo.context_chars) <= parent.context_chars`

and source-specific per-repository allocations must also sum to no more than their parent source budgets.

Allocation policy:

1. guarantee a minimum useful slice to the highest-ranked repository;
2. distribute the remaining budget proportionally by deterministic normalized selector score;
3. cap very low-ranked repositories so a broad workspace cannot starve the best match;
4. if only one repository is selected, preserve the existing single-repo budget exactly;
5. rounding must be deterministic and any remainder assigned by stable repository ordering.

No allocation may be negative or exceed the parent budget.

### 4. Per-repository retrieval

Add a thin orchestration layer rather than duplicating retrieval algorithms.

Preferred module: `ai_workflow/workspace_retrieval.py`.

For each selected repository:

- use its repository root;
- use its repository-specific changed-file list;
- use its allocated budget slice;
- call existing retrieval primitives / `gather_detailed` through a repo-scoped wrapper;
- preserve existing BM25 + RRF + MMR behavior inside a repository;
- preserve provider eligibility and existing structural fallbacks;
- collect repository-local retrieval metadata and evidence state.

The existing single-repository path remains valid and should use the same orchestration API with one selected repo.

### 5. Repository provenance

Every `ContextItem` returned from multi-repo orchestration must carry metadata containing at least:

- `repository_id`;
- `repository_path` (workspace-relative/stable identity, never raw absolute path in portable output);
- `repository_fingerprint`;
- local source/path metadata when available.

Deduplication must be repository-aware. Identical text from two repositories cannot collapse into one item unless both repository provenances remain represented.

### 6. Cross-repository merge

Cross-repo merge happens after per-repo retrieval and before final context packing.

Ranking inputs may include:

- repository selector score;
- existing item score/fused relevance;
- evidence/source class;
- changed-file relevance;
- stable repository and source/path tie-breakers.

The merge must be deterministic. Thread completion order, filesystem enumeration order, and Python hash randomization must not alter the final ranked result.

The final packed context must stay within the original global `ContextBudget`.

### 7. Concurrency and deadline

Independent repository retrieval may execute concurrently, but concurrency is bounded by a small configurable worker count.

Use one global deadline for the whole multi-repo retrieval operation. Per-repository calls receive only the remaining time budget. A slow repository must not extend the overall task deadline.

Determinism rule: concurrency may change wall-clock time only, never final ranking or allocation.

If one repository times out or fails retrieval:

- record its failure in orchestration metadata;
- keep successful evidence from other repositories;
- do not silently expand into unselected repositories;
- do not exceed the deadline while retrying.

No automatic retry loop is part of Stage 3.

## Data flow

`task`
→ existing lane/risk classification
→ Stage 2 active repository set
→ collect cheap repo signals + per-repo changed files
→ deterministic repository selector
→ globally conserved budget allocator
→ bounded per-repo retrieval
→ attach repository provenance
→ deterministic cross-repo merge
→ existing final context pack
→ `brief` / `context` output + telemetry

## CLI / output contract

`ai-workflow brief` and `ai-workflow context` keep current fields for backward compatibility and add an orchestration section containing:

- aggregate workspace fingerprint;
- selected repositories in rank order;
- skipped repositories with reasons;
- selector scores/reason codes;
- per-repository context/source allocation;
- per-repository changed files;
- repository retrieval status;
- repositories searched;
- total allocated vs used budget.

For single-repository workspaces, output remains semantically equivalent to today and additional orchestration metadata is additive.

No new required user command is needed for Stage 3. Existing `repos` commands from Stage 2 control the candidate set.

## Configuration

Add only minimal optional workspace retrieval settings, with safe defaults, for example:

- `workspace.retrieval.max_selected_repositories`;
- `workspace.retrieval.max_workers`;
- `workspace.retrieval.deadline_seconds`;
- `workspace.retrieval.minimum_repo_share`.

Defaults must preserve current single-repo behavior and keep multi-repo work bounded.

Do not require users to manually configure per-repo budgets.

## Error handling and safety

- Invalid/escaped repository roots remain fail-closed through Stage 2 path policy.
- Unaccepted repositories never become candidates.
- A missing/stale index is a weak selector signal, not permission to scan arbitrary neighboring directories.
- Repository content is evidence/data, never executable instructions.
- Provider subprocess trust boundaries remain unchanged.
- Failure in one repository must not corrupt or mutate registry state.
- Selection and budget calculations must be pure/deterministic functions where practical.

## Testing strategy

### Baseline repair tests

- stopword-heavy symbols cannot outrank a CRG-specific candidate solely through grammatical token matches;
- exact symbol matching remains unchanged;
- benchmark threshold is restored without lowering the gate.

### Repository selection tests

- clear task match selects correct secondary repo;
- unrelated repo is skipped;
- primary repo prior wins only genuinely ambiguous ties;
- duplicate folder names with different repo IDs stay distinct;
- selection is deterministic under input-order permutations;
- explicit symbol/endpoint hints influence the correct repo;
- changed files can lift the relevant repo.

### Budget tests

- sum of repository allocations never exceeds parent budget;
- sum of per-source allocations never exceeds parent source budget;
- one-repo allocation equals current budget contract;
- deterministic rounding/remainder behavior;
- ten-repository fixture cannot multiply budget by repository count;
- zero-score/skipped repos receive zero allocation.

### Retrieval/provenance tests

- retrieval runs only on selected repositories;
- each item carries repository ID/path/fingerprint;
- identical text from two repos preserves both provenances;
- repo-specific changed files are passed only to that repo;
- timeout/failure in one repo preserves successful evidence elsewhere;
- concurrency completion order does not change final ranking.

### Benchmark additions

Add measured multi-repo fixtures/metrics:

- `RepoRecall@K`;
- `WrongRepoRate`;
- `FileRecall@K` where gold files exist;
- repositories searched per task;
- global/per-repo budget conservation;
- final context token/char usage;
- deterministic ranking regression;
- at least one 10-repository workspace fixture;
- same-basename/different-repository fixture.

Existing retrieval-quality floors must not be relaxed to make Stage 3 pass.

## Performance constraints

Repository selection must be materially cheaper than full retrieval. It should rely on bounded summaries/index metadata rather than reading full repository contents.

Multi-repo retrieval should use bounded concurrency and one global deadline. Memory usage should scale with selected repositories and bounded candidate counts, not all files from all accepted repositories.

## Compatibility

- Python 3.10–3.14.
- Linux, Windows, macOS.
- Existing `workspace.roots` compatibility remains.
- Existing Stage 2 registry remains authoritative.
- Existing single-root `workspace_fingerprint()` remains unchanged.
- Existing `gather_detailed` behavior remains the repository-local retrieval engine unless a narrow compatibility wrapper is required.
- Core operation remains available without external LLM/API dependencies.

## Proposed files

Primary additions:

- `ai_workflow/workspace_selector.py`
- `ai_workflow/workspace_budget.py`
- `ai_workflow/workspace_retrieval.py`

Likely focused edits:

- `ai_workflow/context_broker.py` — baseline stopword scoring repair and minimal repo-local hooks only;
- `ai_workflow/adaptive_broker.py` — expose repo-scoped retrieval metadata without absorbing orchestration logic;
- `ai_workflow/cli.py` — consume workspace orchestration for `brief`/`context`;
- `ai_workflow/config.py` / control-plane config — validate optional retrieval settings;
- `ai_workflow/models.py` only if a small typed descriptor is clearly cleaner than dictionaries;
- benchmark/test/docs files.

Avoid a broad `Workspace` object refactor in this stage.

## Acceptance criteria

Stage 3 is complete only when all of the following are true:

1. `main` retrieval benchmark regression is repaired without weakening thresholds.
2. At least 10 accepted repositories can coexist while only relevant repositories are searched.
3. A clearly relevant secondary repository can outrank the primary repository.
4. Wrong/unrelated repositories normally receive no retrieval allocation.
5. One parent context budget is conserved across all selected repositories.
6. Repository-specific changed files influence only their owning repository.
7. Every multi-repo context item carries stable repository provenance.
8. Identical source content from different repos does not lose provenance.
9. Retrieval result ordering is stable under repository input order and worker completion order changes.
10. One repository timing out does not extend the global deadline or discard successful evidence from others.
11. Single-repository behavior remains backward compatible.
12. New RepoRecall/WrongRepo/budget-conservation tests and benchmarks pass.
13. Existing benchmark floors do not regress.
14. Full CI is green on Linux/Windows/macOS and Python 3.10–3.14.

## Deferred Stage 4+

After Stage 3 is stable, the next architectural layer can add a deterministic cross-repository intelligence graph (`repo → package → API → test → deploy`) to expand selection through proven dependency edges. Learned/progress-aware routing and bandit-based retriever choice remain later, shadow/offline-first features and never replace the deterministic safety router.
