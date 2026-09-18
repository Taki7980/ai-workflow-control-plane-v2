# Provenance Replay Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify execution identity across retrieval, telemetry, and existing run provenance, then add a minimal immutable debug journal that can verify whether a recorded run is replay-compatible with the current workspace.

**Architecture:** Reuse `RunMetadata`, `RetrievalTrace`, workspace fingerprints, and CRG manifests. Generate the run ID in `WorkflowEngine`, propagate identities into diagnostics/telemetry, let `WorkflowClient` reuse that identity, and add one focused journal module for immutable debug records plus replay-precondition verification.

**Tech Stack:** Python standard library and existing provenance/telemetry/workspace/CRG helpers. No new runtime dependency.

**Spec:** `docs/research/2026-09-18-pr-11-provenance-replay-observability.md`

## Global Constraints

- [ ] Reuse existing `RunMetadata`; do not create a competing provenance model.
- [ ] Public `WorkflowClient.prepare()` stays side-effect-free unless persistence/telemetry is explicitly enabled.
- [ ] No raw task text in local journal records.
- [ ] No raw evidence text in local journal records.
- [ ] No network authority or new runtime dependency.
- [ ] Journal records are immutable per run ID.
- [ ] Existing config schema remains backward compatible.
- [ ] Existing CI coverage/Ruff/mypy/security/platform/benchmark gates remain unchanged.

---

### Task 1 — RED: universal run identity

**Files:**
- Modify: `tests/test_workflow_engine.py`
- Modify: `tests/test_telemetry.py`
- Modify: `tests/test_final_audit_target.py`

**Interfaces:**
- Produces: `diagnostics["run_id"]`
- Produces: `RetrievalTrace.run_id`
- Requires: `WorkflowResult.run.run_id == retrieval["run_id"]`

- [ ] Add a workflow-engine test asserting every retrieval returns a non-empty stable run ID.
- [ ] Add a telemetry test asserting the local trace payload contains the supplied run ID.
- [ ] Add a public API test asserting `RunMetadata` reuses the retrieval run ID.
- [ ] Run targeted tests and confirm RED failures.

### Task 2 — RED: policy/workspace/graph identity

**Files:**
- Modify: `tests/test_workflow_engine.py`
- Modify: `tests/test_final_audit_target.py`
- Modify: `tests/test_code_review_graph.py`

**Interfaces:**
- Produces: `diagnostics["policy_identity"]`
- Produces: `diagnostics["graph_state"]`
- Produces: `RunMetadata.graph_fingerprint`

- [ ] Assert policy identity contains canonical config digest and policy version.
- [ ] Assert graph identity is stable for equivalent path-independent graph manifest state.
- [ ] Assert absent/stale graph state fails closed without breaking retrieval.
- [ ] Assert `RunMetadata.reproducibility_key()` changes when graph fingerprint changes.
- [ ] Run targeted tests and confirm RED failures.

### Task 3 — Implement identity bridge

**Files:**
- Modify: `ai_workflow/workflow_engine.py`
- Modify: `ai_workflow/telemetry.py`
- Modify: `ai_workflow/api.py`
- Modify: `ai_workflow/provenance.py`

**Interfaces:**
- `WorkflowEngine.gather_detailed_async(..., run_id: str | None = None)`
- `RetrievalTrace(..., run_id: str, ...)`
- Backward-compatible `RunMetadata.graph_fingerprint: str = "unknown"`

- [ ] Generate UUID run ID in the engine when caller does not supply one.
- [ ] Put it in diagnostics and `RetrievalTrace`.
- [ ] Compute canonical config/policy identity once per run.
- [ ] Make `WorkflowClient` pass/reuse the retrieval run ID.
- [ ] Extend `RunMetadata` schema compatibly so old schema-v1 records load with graph fingerprint `"unknown"`.
- [ ] Keep `reproducibility_key()` content-based and independent of random run ID.

### Task 4 — Aggregate CRG graph identity

**Files:**
- Modify: `ai_workflow/code_review_graph.py`
- Modify: `tests/test_code_review_graph.py`

**Interfaces:**
- `workspace_graph_fingerprint(workspace_root: Path, config: dict | None = None) -> dict[str, Any]`

- [ ] Build sorted per-repository graph identity rows from existing central graph freshness/manifest state.
- [ ] Exclude absolute checkout paths from the digest.
- [ ] Include graph SHA-256, repository fingerprint, Git HEAD, and graph schema when valid.
- [ ] Represent missing/stale graphs explicitly without raising.
- [ ] Hash canonical JSON using SHA-256.
- [ ] Add result to retrieval diagnostics and trace.

### Task 5 — Immutable debug/replay journal

**Files:**
- Create: `ai_workflow/run_journal.py`
- Create: `tests/test_run_journal.py`
- Modify: `ai_workflow/workflow_engine.py`

**Interfaces:**
- `write_run_journal(root: Path, record: dict[str, Any]) -> str`
- `read_run_journal(root: Path, run_id: str) -> dict[str, Any] | None`
- `verify_run_journal(root: Path, run_id: str, config: dict) -> dict[str, Any]`

- [ ] Write one immutable JSON document per run under `ai-workspace/generated/run-journal/`.
- [ ] Reject unsafe run IDs.
- [ ] Store identity + bounded retrieval diagnostics only.
- [ ] Store selected evidence descriptors/provenance, never `ContextItem.text`.
- [ ] Replay verification recomputes config/workspace/graph identities and reports exact mismatches.
- [ ] Journal only when existing telemetry/write path is enabled.

### Task 6 — Thin inspection CLI

**Files:**
- Create: `ai_workflow/run_cli.py`
- Create: `tests/test_run_cli.py`
- Modify: `ai_workflow/entrypoint.py`

**Interfaces:**
- `ai-workflow run inspect <run-id>`
- `ai-workflow run verify <run-id>`

- [ ] Route only the two new commands through the thin package entrypoint.
- [ ] `inspect` prints the stored journal record.
- [ ] `verify` prints replay-compatibility/mismatch information.
- [ ] No tool/provider execution during verify.

### Task 7 — Verify and open PR

- [ ] Run targeted unit tests.
- [ ] Run full unit suite.
- [ ] Run Ruff whole repository.
- [ ] Run mypy whole package.
- [ ] Verify branch coverage remains >=80%.
- [ ] Verify Security, Tests, CodeQL, package/platform and benchmark jobs.
- [ ] Update PR body with actual evidence.
- [ ] Mark ready only when all required checks are green.
