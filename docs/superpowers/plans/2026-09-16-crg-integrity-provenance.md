# PR-01 Code Review Graph Integrity & Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Code Review Graph count as ready only when its SQLite database is structurally valid and meaningfully populated, record reproducible graph provenance, and prevent graph storage from escaping the managed workspace.

**Architecture:** Keep CRG as an optional external provider. Add a small stdlib-only SQLite validator and manifest writer inside the existing CRG boundary, reuse the existing workspace fingerprint contract for provenance, and add one pinned real-CRG CI contract test. Do not change retrieval policy or structural sufficiency in this PR.

**Tech Stack:** Python standard library (`sqlite3`, `hashlib`, `json`), existing `ai_workflow` helpers, GitHub Actions, Code Review Graph 2.3.8 for the pinned compatibility job.

**Spec:** Deep research report dated 2026-09-16; PR-01 issues I-001 through I-004.

## Global Constraints

- Keep the runtime dependency-free.
- Preserve centralized CRG storage under `ai-workspace/code-review-graph/<repo-key>/`.
- Do not change structural retrieval/routing policy in this PR.
- Treat the CRG SQLite schema as an external contract: require only the stable `nodes`, `edges`, `metadata` tables and schema version >= 10.
- Fail closed on corrupt/empty graph databases.
- Keep compatibility with repositories that legitimately have zero relationship edges; the real integration fixture must prove edges are produced for code that contains a call relationship.
- Never follow a CRG data-directory symlink outside the workspace.

---

### Task 1: Regression tests for invalid graph acceptance and storage escape

**Files:**
- Modify: `tests/test_code_review_graph.py`

**Interfaces:**
- Consumes: `sync_workspace_graphs()`, `repository_data_dir()`
- Produces: regression tests that fail on the current implementation

- [ ] **Step 1: Add a helper that creates a minimal schema-v10 graph with nodes/edges/metadata.**
- [ ] **Step 2: Add a test proving an empty placeholder `graph.db` is rejected.**
- [ ] **Step 3: Add a test proving successful sync writes `manifest.json`.**
- [ ] **Step 4: Add a test proving a symlinked CRG storage root that escapes the workspace is rejected.**
- [ ] **Step 5: Run the tests and verify the new assertions fail against the pre-fix implementation.**

### Task 2: Minimal graph validator and provenance manifest

**Files:**
- Modify: `ai_workflow/code_review_graph.py`
- Create: `scripts/validate_crg_graph.py`

**Interfaces:**
- Produces: `validate_graph_database(path, minimum_schema_version=10)`
- Produces: manifest schema 1 beside every successfully built/refreshed `graph.db`

- [ ] **Step 1: Open SQLite read-only and require `PRAGMA quick_check = ok`.**
- [ ] **Step 2: Require `nodes`, `edges`, and `metadata`; require schema version >= 10 and at least one node.**
- [ ] **Step 3: Hash `graph.db` with SHA-256.**
- [ ] **Step 4: Record repository fingerprint, Git HEAD, CRG version, CRG schema, graph hash, node/edge counts, action, and UTC generation time in `manifest.json`.**
- [ ] **Step 5: Make sync readiness depend on validation rather than file existence.**
- [ ] **Step 6: Make health report validation failures instead of accepting an invalid database.**

### Task 3: Safe managed graph directory

**Files:**
- Modify: `ai_workflow/code_review_graph.py`

**Interfaces:**
- Consumes: `resolve_within_root()`
- Produces: a confined central CRG path

- [ ] **Step 1: Resolve the central graph path through the existing path policy.**
- [ ] **Step 2: Reject a symlink that resolves outside the workspace.**
- [ ] **Step 3: Re-run the storage-escape regression test.**

### Task 4: Real Code Review Graph contract test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_code_review_graph_real.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: published `code-review-graph==2.3.8`
- Produces: a real temporary Git repository whose graph must contain nodes and at least one `CALLS` edge

- [ ] **Step 1: Build a tiny committed Python repository with `handle() -> helper()` and a test.**
- [ ] **Step 2: Run `sync_workspace_graphs()` without mocking the CRG process.**
- [ ] **Step 3: Validate the produced database and manifest.**
- [ ] **Step 4: Query SQLite in the pinned compatibility test and require a `CALLS` relationship.**
- [ ] **Step 5: Add a dedicated CI job that installs CRG 2.3.8 and runs the integration test.**

### Task 5: Verification and PR gate

**Files:** no additional production files

- [ ] **Step 1: Run targeted CRG unit tests.**
- [ ] **Step 2: Run the real CRG integration job.**
- [ ] **Step 3: Run the full unit suite.**
- [ ] **Step 4: Run compile/quality checks applicable to touched Python files.**
- [ ] **Step 5: Inspect the PR diff for generated databases/manifests or accidental local state.**
- [ ] **Step 6: Raise PR only after green verification; do not merge automatically.**
