# Multi-Repository Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:test-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Make a non-Git control workspace with nested independent Git repositories behave as a true multi-repository workspace: discover Git repositories correctly, keep repository indexes isolated, avoid cross-repository source scanning, and make strict health checks validate every active repository.

**Architecture:** Keep the outer folder as the control-plane workspace and treat only actual Git worktrees as repository retrieval roots when active repositories exist. Store lightweight indexes centrally under the control workspace, keyed by repository-relative identity, while keeping single-repository compatibility at `ai-workspace/generated`. Use Git commands as the authoritative metadata reader when Git is available so worktrees, gitfiles, reftable refs, detached HEADs, and future ref-storage changes are handled by Git itself.

**Tech Stack:** Python 3.10+, Git CLI, unittest, existing repository registry/indexer/workspace/doctor abstractions.

**Spec:** Hardening tracker PR-03 / I-009–I-012 and the 2026-09-16 research review.

## Global Constraints

- Do not change PR-04+ concerns.
- Preserve existing single-repository behavior.
- Keep nested code repositories clean; central control-plane state belongs under the outer `ai-workspace/`.
- Fail closed on ambiguous or invalid repository metadata.
- Support both `.git` directories and Git gitfiles used by linked worktrees/submodules.
- Prefer Git plumbing/porcelain over manually interpreting ref storage when Git is available.
- Keep all new repository state path-confined to the control workspace.
- TDD: regression tests must fail on merged `main` before implementation.
- Do not merge the PR automatically.

---

### Task 1: Git-native repository metadata

**Files:**
- Modify: `ai_workflow/repository_registry.py`
- Test: `tests/test_repository_registry.py`

**Interfaces:**
- Consumes: repository directories discovered by `discover_repositories()`.
- Produces: authoritative `RepositorySpec.git_dir`, `remote_identity`, `head_ref`, and `head_sha`.

- [ ] Add a real-Git regression test using `git init --ref-format=reftable` when the installed Git supports it. Assert discovery returns the committed HEAD SHA and branch.
- [ ] Verify the test fails on the existing manual refs reader.
- [ ] Add bounded Git command helpers using `git -C <repo>` / cwd and use `rev-parse --absolute-git-dir`, `symbolic-ref --quiet HEAD`, `rev-parse HEAD`, and `config --get remote.origin.url`.
- [ ] Keep the current filesystem parser as a fallback only when Git is unavailable or the Git probe cannot run.
- [ ] Run repository registry tests and compatibility tests.

### Task 2: Non-Git control-root isolation

**Files:**
- Modify: `ai_workflow/workspace.py`
- Test: `tests/test_multirepo_isolation.py`

**Interfaces:**
- Consumes: accepted registry entries.
- Produces: `workspace_roots(root, config)` containing only actual repository roots when active Git repositories exist.

- [ ] Add a regression test for `RevenueOS/{admin-panel,backend}` where `RevenueOS` is not Git and both children are Git.
- [ ] Assert `workspace_roots()` returns only the two Git repositories and never the non-Git parent.
- [ ] Preserve the control root for backward compatibility only when it is itself Git or when no active Git repository exists.
- [ ] Run workspace/repository tests.

### Task 3: Central per-repository lightweight indexes

**Files:**
- Modify: `ai_workflow/indexer.py`
- Modify: `ai_workflow/bootstrap.py`
- Modify: `ai_workflow/cli.py`
- Modify: `ai_workflow/context_broker.py`
- Modify: `ai_workflow/semantic.py`
- Test: `tests/test_multirepo_isolation.py`
- Test: `tests/test_indexer.py`

**Interfaces:**
- Produces: `index_data_dir(repository_root)` resolving to:
  - single Git root/control root: `ai-workspace/generated`
  - nested repository: `<control-root>/ai-workspace/indexes/<repository-key>`
- Produces: workspace-level index build/incremental helpers returning per-repository results.

- [ ] Add setup regression: non-Git parent + two child repos creates two central index states and no `ai-workspace/` inside either child.
- [ ] Add root-Git + nested-Git regression: parent index must not contain nested repository source files.
- [ ] Verify both regressions fail on current behavior.
- [ ] Replace `Path.rglob` repository scanning with a bounded walk that prunes nested Git roots.
- [ ] Route `build_indexes`, `incremental_indexes`, `load_state`, lightweight retrieval, and built-in semantic retrieval through the repository index data directory.
- [ ] Make setup and `ai-workflow index` index all active repository roots, with aggregate backward-compatible counters plus per-repository detail.
- [ ] Keep project-level memory/research/hot-cache reads anchored to the outer control workspace rather than child repos.
- [ ] Run indexer/context/semantic/CLI tests.

### Task 4: Per-repository strict doctor

**Files:**
- Modify: `ai_workflow/doctor.py`
- Test: `tests/test_doctor.py`
- Test: `tests/test_multirepo_isolation.py`

**Interfaces:**
- Produces: `repository_indexes` health entries with repository root/relative path, index presence, tracked file count, and stale file count.
- `core_ok` is false when any active repository has a missing or stale lightweight index.

- [ ] Add a two-repository doctor regression and assert both repositories are reported independently.
- [ ] Mutate one repo after indexing and assert only that repo is stale and strict health fails.
- [ ] Preserve aggregate `index.present/tracked_files/stale_files` for compatibility.
- [ ] Add repo-specific remediation messages.
- [ ] Run doctor/CLI tests.

### Task 5: End-to-end RevenueOS-shape smoke and verification

**Files:**
- Test: `tests/test_multirepo_isolation.py`
- Modify only if a failing integration test identifies a root cause.

- [ ] Build a non-Git outer workspace with `admin-panel` and `backend` Git repos.
- [ ] Run setup.
- [ ] Assert registry discovers/activates both repos.
- [ ] Assert workspace retrieval roots are exactly both repos.
- [ ] Assert each repo has an isolated central lightweight index.
- [ ] Assert CRG data directories remain distinct per repo.
- [ ] Assert strict doctor is healthy, then mutate one repository and assert strict doctor fails for that repository.
- [ ] Run full test matrix, benchmark regression, real CRG contract, package smoke, and security workflow.
- [ ] Review the PR diff for scope creep.
- [ ] Open PR-03 and leave it unmerged for explicit approval.
