# Reproducible Provenance, Cache, and Library API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the audit's remaining application-boundary recommendations: explicit execution semantics, safe deterministic retrieval caching, immutable run provenance, external artifact/lineage vocabulary, async adapters, and a public Python library API.

**Architecture:** Keep the zero-dependency modular monolith. Add small domain modules for semantics, cache identity/storage, provenance/run storage, and public API types. Preserve all existing synchronous compatibility APIs while exposing async provider adapters and `WorkflowClient.prepare()` as the supported programmatic boundary.

**Tech Stack:** Python 3.10+ standard library, asyncio, dataclasses, Protocols, JSON, atomic file I/O, unittest.

**Spec:** Technical Audit and Improvement Plan for `ai-workflow-control-plane-v2` (saved research paper).

## Global Constraints

- Python >=3.10.
- No mandatory runtime dependencies.
- External providers are non-cacheable unless they explicitly declare deterministic + cacheable semantics.
- Cache keys include retrieval-policy version, deterministic workspace identity, provider identity/version, and canonical request parameters.
- `run_id` is random per execution; workspace/content identity is deterministic.
- External model/data systems are represented only through portable artifact references; no MLflow/DVC/OpenLineage dependency.
- Existing CLI and synchronous provider APIs remain compatible.
- Repository content remains untrusted data.

---

### Task 1: Provider execution semantics

**Files:**
- Create: `ai_workflow/execution_semantics.py`
- Modify: `ai_workflow/provider_runner.py`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Produces: `ProviderSemantics`, `cache_eligible()`, provider `version` and `semantics` fields.

- [ ] Write failing tests proving defaults are non-cacheable and side-effecting providers cannot be cached.
- [ ] Run the tests and confirm RED because the contracts do not exist.
- [ ] Implement frozen execution semantics and safe config parsing.
- [ ] Run focused and full tests.
- [ ] Commit.

### Task 2: Canonical retrieval cache

**Files:**
- Create: `ai_workflow/retrieval_cache.py`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Consumes: `ProviderSemantics`, `RetrievalRequest`, deterministic workspace fingerprint.
- Produces: `retrieval_cache_key()`, `FileRetrievalCache`.

- [ ] Write failing tests for canonical-key stability, provider-version invalidation, and cache eligibility.
- [ ] Verify RED.
- [ ] Implement SHA-256 canonical keys and atomic JSON cache entries keyed only by eligible provider executions.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 3: Immutable run provenance and lineage vocabulary

**Files:**
- Create: `ai_workflow/provenance.py`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Produces: `ArtifactReference`, `RunMetadata`, `RunStore`, `LocalRunStore`, `config_digest()`, `changed_files_digest()`, `to_openlineage()`.

- [ ] Write failing tests showing run IDs differ while deterministic metadata digests remain equal.
- [ ] Verify RED.
- [ ] Implement immutable one-file-per-run storage using atomic create semantics.
- [ ] Map workflow/run/job/dataset concepts to an OpenLineage-compatible dictionary without importing OpenLineage.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 4: Async provider adapter boundary

**Files:**
- Modify: `ai_workflow/retrieval_contracts.py`
- Create: `ai_workflow/retrieval_adapters.py`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Produces: `AsyncRetriever` protocol and adapters for synchronous local/CRG/memory providers and typed semantic/external result callables.

- [ ] Write failing adapter tests that preserve provider name/result ordering and isolate synchronous work behind `asyncio.to_thread`.
- [ ] Verify RED.
- [ ] Implement adapters without removing existing sync `Retriever`.
- [ ] Verify GREEN.
- [ ] Commit.

### Task 5: Public Python library API

**Files:**
- Create: `ai_workflow/api.py`
- Modify: `ai_workflow/__init__.py`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Produces: frozen `TaskRequest`, frozen `WorkflowResult`, `WorkflowClient.prepare()`.

- [ ] Write failing tests using an injected engine and real routing/config types.
- [ ] Verify RED.
- [ ] Implement a library peer of the CLI that performs classification/budget/provider detection and calls `WorkflowEngine.gather_detailed_async()`.
- [ ] Export only stable public contracts from package root.
- [ ] Verify GREEN and full compatibility.
- [ ] Commit.

### Task 6: Wire run provenance and document contracts

**Files:**
- Modify: `ai_workflow/workflow_engine.py`
- Modify: `docs/provider-protocol.md`
- Create: `docs/reproducibility.md`
- Test: `tests/test_provenance_cache_library.py`

**Interfaces:**
- Consumes: `LocalRunStore`, provider versions/semantics, workspace state.
- Produces: run metadata in workflow diagnostics and immutable local run record when enabled.

- [ ] Add a failing integration test for run metadata fields and random-vs-deterministic identity separation.
- [ ] Verify RED.
- [ ] Wire provenance at the application boundary with no raw secret-bearing task persistence beyond the privacy policy.
- [ ] Document provider semantics/cache safety and reproducibility fields.
- [ ] Verify the complete Linux/Windows CI matrix.
- [ ] Commit.
