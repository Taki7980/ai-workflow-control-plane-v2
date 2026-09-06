# Adaptive Retrieval V2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add query-aware retrieval intent, optional semantic retrieval, deterministic evidence sufficiency, provenance/tracing, and stronger retrieval benchmarks without adding required runtime dependencies.

**Architecture:** Preserve deterministic lane/risk routing and hard context ceilings. Add a retrieval planner that chooses exact/semantic/structural/mixed paths, a command-based optional semantic provider, deterministic sufficiency scoring, richer ContextItem provenance, and benchmark/CI coverage.

**Tech Stack:** Python 3.10+ stdlib, existing BM25/RRF/MMR implementation, optional external semantic command, optional Code Review Graph.

**Spec:** `docs/superpowers/specs/2026-09-07-adaptive-retrieval-v21-design.md`

## Global Constraints

- Python 3.10+.
- No required runtime dependencies.
- Missing semantic/CRG providers must degrade safely.
- Existing high-risk deterministic routing remains authoritative.
- Hard lane context ceilings remain enforced.
- Answer mode remains side-effect-free by default.

---

### Task 1: Retrieval planning and sufficiency

**Files:**
- Create: `ai_workflow/retrieval_policy.py`
- Test: `tests/test_retrieval_policy.py`

**Interfaces:**
- Produces: `RetrievalIntent`, `RetrievalPlan`, `classify_retrieval_intent()`, `evaluate_sufficiency()`.

- [ ] Add tests for exact, semantic, structural, mixed intent classification and bounded sufficiency.
- [ ] Implement deterministic intent classification and evidence sufficiency.
- [ ] Run focused tests.

### Task 2: Optional semantic provider

**Files:**
- Create: `ai_workflow/semantic.py`
- Modify: `ai_workflow/providers.py`
- Test: `tests/test_semantic.py`

**Interfaces:**
- Consumes configured command from `context.semantic.command` or `AI_WORKFLOW_SEMANTIC_CMD`.
- Produces ranked `ContextItem` candidates with provenance metadata.

- [ ] Test absent, successful, malformed, and timed-out providers.
- [ ] Implement JSON stdin/stdout command contract with safe timeout and result caps.
- [ ] Extend provider status with semantic readiness.

### Task 3: Provenance-aware adaptive broker

**Files:**
- Modify: `ai_workflow/models.py`
- Modify: `ai_workflow/context_broker.py`
- Test: `tests/test_context_broker.py`
- Create: `tests/test_adaptive_retrieval.py`

**Interfaces:**
- Consumes `RetrievalPlan` and semantic provider.
- Produces context items annotated with retriever/trust/provenance/selection metadata.

- [ ] Add provenance fields without breaking existing serialization.
- [ ] Route structural queries to CRG, semantic/mixed queries to semantic provider, and exact queries to lexical retrieval.
- [ ] Evaluate sufficiency after cheap stages and stop early when justified.
- [ ] Preserve targeted-source fallback and hard final budget.

### Task 4: Trace telemetry

**Files:**
- Create: `ai_workflow/telemetry.py`
- Modify: `ai_workflow/context_broker.py`
- Modify: `ai_workflow/cli.py`
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Produces compact JSON traces for mutation/full workflows; opt-in trace for answers.

- [ ] Add trace schema and atomic writer.
- [ ] Record intent, provider attempts, latency, sufficiency, candidate counts, and budget usage.
- [ ] Expose trace metadata in `brief`/`context` output without forcing filesystem writes for Answer.

### Task 5: Configuration and validation

**Files:**
- Modify: `ai-workspace/config/control-plane.json`
- Modify: `ai_workflow/config.py`
- Test: `tests/test_config.py`

- [ ] Add semantic, retrieval-planner, sufficiency, adaptive-budget, telemetry configuration.
- [ ] Validate timeouts, thresholds, caps, and enum-like mode values.

### Task 6: Benchmark expansion and comparison

**Files:**
- Modify: `benchmarks/sample-tasks.json`
- Modify: `ai_workflow/benchmark.py`
- Modify: `tests/test_benchmark_metrics.py`
- Create: `tests/test_benchmark_dataset.py`

- [ ] Expand to at least 24 balanced cases spanning exact, semantic, structural, mixed, ambiguous, stale/negative scenarios.
- [ ] Add query-type grouped metrics and escalation/sufficiency statistics.
- [ ] Preserve warning that retrieval metrics are not downstream correctness.

### Task 7: CI and documentation

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

- [ ] Add dependency-free benchmark regression command to CI.
- [ ] Document semantic provider contract, adaptive routing, traces, and benchmark limitations.
- [ ] Run full unit test suite, strict doctor, benchmark, and diff checks.
