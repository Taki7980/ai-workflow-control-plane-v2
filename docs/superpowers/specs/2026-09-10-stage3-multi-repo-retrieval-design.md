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

Signal priority is contractual even if numeric weights remain implementation details:

1. explicit symbol/endpoint evidence;
2. changed-file evidence;
3. repository identity/path/name evidence;
4. indexed symbol/file-path lexical evidence;
5. primary-repository prior.

The primary prior is only a final weak preference. It must not outrank a secondary repository with stronger explicit, changed-file, identity, or indexed evidence.

Selection output includes a reason breakdown so `brief`/telemetry can explain why a repository was selected or skipped.

Unrelated repositories should normally receive score zero and no retrieval budget. At most three repositories are selected by default.

### 3. One global budget

Add `ai_workflow/workspace_budget.py`.

The lane-level `ContextBudget` remains the hard parent ceiling. Stage 3 allocates slices to selected repositories; it never creates one full budget per repository.

Required invariants:

`sum(repo.context_chars) <= parent.context_chars`

and, for each source class:

`sum(repo.source_chars[source]) <= parent.source_chars[source]`

Allocation policy:

1. if only one repository is selected, it receives the existing parent budget exactly;
2. with multiple repositories, the highest-ranked repository receives at least 50% of the parent context budget;
3. the remaining budget is distributed proportionally by deterministic normalized selector score across all selected repositories, while respecting the 50% floor for rank 1;
4. source-specific budgets use the same final repository allocation ratios and deterministic integer rounding;
5. any rounding remainder is assigned in stable repository-rank order;
6. zero-score/skipped repositories receive zero allocation;
7. no allocation may be negative or exceed its parent budget.

The 50% top-repository floor is an internal deterministic policy in Stage 3, not a user-facing tuning knob.

### 4. Per-repository retrieval

Add a thin orchestration layer rather than duplicating retrieval algorithms.

Module: `ai_workflow/workspace_retrieval.py`.

For each selected repository:

- use its repository root;
- use its repository-specific changed-file list;
- use its allocated budget slice;
- call existing retrieval primitives / `gather_detailed` through a repo-scoped wrapper;
- preserve existing BM25 + RRF + MMR behavior inside a repository;
- preserve provider eligibility and existing structural fallbacks;
- collect repository-local retrieval metadata and evidence state.

The existing single-repository path remains valid and uses the same orchestration API with one selected repo.

### 5. Repository provenance

Every `ContextItem` returned from multi-repo orchestration must carry metadata containing at least:

- `repository_id`;
- `repository_path` (workspace-relative/stable identity, never raw absolute path in portable output);
- `repository_fingerprint`;
- local source/path metadata when available.

Deduplication must be repository-aware. Identical text from two repositories cannot collapse into one item unless both repository provenances remain represented.

### 6. Cross-repository merge

Cross-repo merge happens after per-repo retrieval and before final context packing.

The ordering contract is:

1. repository-local retrieval relevance remains primary;
2. repository selector score is the secondary preference when local relevance is tied/equivalent;
3. changed-file evidence may break otherwise equivalent relevance in favor of the repository owning the changed file;
4. remaining ties are resolved deterministically by repository ID, source type, normalized source path, then dedupe key.

The implementation may reuse the existing fusion/diversification helpers, but it must preserve that ordering contract and must not make thread completion order observable in the result.

The final packed context must stay within the original global `ContextBudget`.

### 7. Concurrency and deadline

Independent repository retrieval may execute concurrently, but concurrency is bounded.

Default Stage 3 settings:

- `workspace.retrieval.max_selected_repositories = 3`
- `workspace.retrieval.max_workers = 3`
- `workspace.retrieval.deadline_seconds = 12`

Use one monotonic global deadline for the whole multi-repo retrieval operation. Per-repository calls receive only the remaining time budget. A slow repository must not extend the overall task deadline.

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

Stage 3 adds exactly these optional settings under `workspace.retrieval`:

- `max_selected_repositories` — positive integer, default `3`;
- `max_workers` — positive integer, default `3`;
- `deadline_seconds` — positive number, default `12`.

Validation must reject zero/negative values and clamp effective worker count to selected-repository count.

No per-repository budget configuration is introduced in Stage 3.

Defaults preserve current single-repository behavior and keep multi-repository work bounded.

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
- top-ranked repo receives at least 50% in multi-repo mode;
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

Multi-repo retrieval uses at most three workers and one 12-second global deadline by default. Memory usage must scale with selected repositories and bounded candidate counts, not all files from all accepted repositories.

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

Focused edits:

- `ai_workflow/context_broker.py` — baseline stopword scoring repair and minimal repo-local hooks only;
- `ai_workflow/adaptive_broker.py` — expose repo-scoped retrieval metadata without absorbing orchestration logic;
- `ai_workflow/cli.py` — consume workspace orchestration for `brief`/`context`;
- `ai_workflow/config.py` and control-plane config — validate the three optional retrieval settings;
- `ai_workflow/models.py` only if a small immutable repository descriptor avoids dictionary coupling;
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
