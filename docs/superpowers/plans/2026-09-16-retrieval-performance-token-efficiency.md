# Retrieval Performance and Token Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce retrieval CPU and make context selection optimize the same token-cost model used by model-facing benchmark budgets, while proving retrieval quality does not regress.

**Architecture:** Keep the current retrieval stack, hard character safety ceiling, source truncation, and ranking semantics. Precompute BM25 term frequencies once during fit; make selector economics token-aware through the existing provider-neutral `TokenEstimator`; and add a deterministic reference-parity performance benchmark alongside the existing end-to-end quality regression gate.

**Tech Stack:** Python 3.11+, `collections.Counter`, existing `TokenEstimator` / `CharacterTokenEstimator`, unittest, GitHub Actions benchmark regression.

**Spec:** PR-06 / I-022–I-024 from the AI Workflow v2 hardening tracker, grounded in the 2026-09-15 repository research report plus current 2026 Agent Retrieval Bench / ContextBench / token-efficiency research.

## Global Constraints

- Preserve BM25 ranking semantics.
- Preserve the zero-runtime-dependency Python core.
- Preserve the existing hard character ceiling and truncation behavior as a compatibility/safety bound.
- Use the existing shared token-estimator abstraction; do not create a second token-count approximation.
- Token-aware selection must be deterministic.
- Do not hard-gate CI on wall-clock speed because hosted-runner timing is noisy.
- Performance evidence must include ranking/score parity with the pre-optimization reference behavior.
- Existing benchmark regression remains the blocking end-to-end quality gate for density, yield, and estimated context volume.
- No new retrieval provider in PR-06.
- No external-provider security changes in PR-06.
- Do not merge automatically.

---

### Task 1: Precompute BM25 term frequencies — I-022

**Files:**
- Modify: `ai_workflow/math_retrieval.py`
- Test: `tests/test_retrieval_performance.py`

**Interfaces:**
- `TokenizedDoc.term_freq: dict[str, int]`
- `BM25Scorer.fit()` computes term frequencies once.
- `BM25Scorer.score_document()` performs dictionary lookup, never `list.count()`.

- [ ] Add a failing test proving fitted docs expose the expected term frequencies.
- [ ] Add a failing test using a token list whose `.count()` raises, proving scoring cannot rescan it.
- [ ] Add `Counter(tokens)` during fit.
- [ ] Replace repeated token-list scans with `doc.term_freq.get(term, 0)`.
- [ ] Run focused BM25 tests and confirm ranking behavior is unchanged.

### Task 2: Token-aware facility-location selection — I-023

**Files:**
- Modify: `ai_workflow/context_selection.py`
- Modify: `ai_workflow/workflow_engine.py`
- Test: `tests/test_retrieval_performance.py`
- Preserve: `tests/test_context_selection.py`

**Interfaces:**
- Selector accepts optional `budget_tokens` and optional `TokenEstimator`.
- Candidate carries both character cost and token cost.
- Gain-per-cost and token-budget inclusion use token cost when a token budget is provided.
- Character ceiling remains independently enforced.
- Diagnostics add `used_tokens` and `budget_tokens` while retaining existing character diagnostics.

- [ ] Add a failing test with an injected estimator that makes two equal-relevance candidates have different token costs.
- [ ] Add a failing test proving the character hard cap still blocks oversized content even when token cost is low.
- [ ] Compute candidate token cost through the shared estimator.
- [ ] Use token cost for facility-location economics and token-budget admission.
- [ ] Derive an adaptive token ceiling in `WorkflowEngine` using the same adaptive fraction as the existing character ceiling.
- [ ] Pass both adaptive char and token ceilings into the selector.
- [ ] Preserve legacy direct callers that only provide a character budget.
- [ ] Run existing selector/broker/engine tests.

### Task 3: Deterministic retrieval performance regression evidence — I-024

**Files:**
- Create: `scripts/check_retrieval_performance.py`
- Modify: `.github/workflows/tests.yml`
- Test: `tests/test_retrieval_performance.py`

**Interfaces:**
- Script builds a deterministic synthetic code-search corpus and fixed queries.
- Reference scorer reproduces the old repeated-`list.count()` BM25 calculation.
- Optimized scorer must match reference ranking exactly and scores within a tight numerical tolerance.
- JSON output reports corpus size, query count, ranking parity, max score delta, reference elapsed time, optimized elapsed time, and observed speedup.
- Wall-clock speed is informational only; parity failures are blocking.
- Existing `scripts/check_benchmark_regression.py` remains the end-to-end blocking quality gate.

- [ ] Add a failing test because the script does not exist.
- [ ] Implement deterministic reference/optimized comparison.
- [ ] Fail the script on ranking mismatch or excessive score delta.
- [ ] Report timing without asserting a minimum speedup.
- [ ] Add the script to the benchmark-regression CI job.
- [ ] Run the existing benchmark regression to ensure relevant-item density, pattern yield, and estimated context tokens remain within policy.

### Final verification

- [ ] Run full unit suite across the supported Python/platform matrix.
- [ ] Run quality gate.
- [ ] Run package/install smoke jobs.
- [ ] Run real CRG contract.
- [ ] Run deterministic retrieval performance parity check.
- [ ] Run end-to-end benchmark regression.
- [ ] Run Python security, secret scan, and container scan.
- [ ] Review the PR diff for PR-07+ scope creep.
- [ ] Mark PR ready only after all exact-head gates are green.
- [ ] Leave PR unmerged for explicit human approval.
