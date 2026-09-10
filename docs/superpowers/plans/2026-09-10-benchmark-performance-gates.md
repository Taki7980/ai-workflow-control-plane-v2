# Benchmark Regression and Performance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing benchmark smoke test into a reproducible regression gate and add measured performance evidence for concurrency and the conditional P3 daemon/hot-cache decision.

**Architecture:** Keep benchmark execution in-process and dependency-free. Add reusable regression-policy and profiling modules, record quality/per-query floors separately from noisy efficiency tolerance, report p50/p95/p99 without making timing a hard gate until enough data exists, and emit a machine-readable P3 decision artifact.

**Tech Stack:** Python 3.10+ standard library, statistics, time, JSON, unittest, GitHub Actions.

**Spec:** Technical Audit and Improvement Plan for `ai-workflow-control-plane-v2`.

## Global Constraints

- Do not invent quality thresholds; baseline values must come from measured repository benchmark runs.
- Correctness floors are blocking; noisy efficiency regressions use relative tolerance.
- Per-query-type floors are enforced where a metric has measured support.
- Timing distributions are reported before being promoted to hard CI gates.
- Concurrency evidence must preserve deterministic equivalent context for deterministic providers.
- P3 daemon/hot-cache implementation is allowed only after a measured repeated-call profile crosses the documented material-benefit threshold.

---

### Task 1: Regression policy
- [ ] Write failing tests for correctness floors, relative tolerance, and per-query floors.
- [ ] Verify RED.
- [ ] Implement `ai_workflow/benchmark_regression.py` and a CLI script wrapper.
- [ ] Verify GREEN.

### Task 2: Tail-latency instrumentation
- [ ] Write failing tests for p50/p95/p99 summaries and per-query evidence/abstention metrics.
- [ ] Verify RED.
- [ ] Extend `benchmark.py` without changing existing keys.
- [ ] Verify GREEN.

### Task 3: Measured baseline
- [ ] Run the repository benchmark repeatedly on the branch/current main-compatible code.
- [ ] Record measured correctness/per-query floors in `benchmarks/baseline.json`; no guessed values.
- [ ] Add non-blocking performance reference data and relative efficiency tolerance.
- [ ] Verify the checker accepts the baseline against itself.

### Task 4: Concurrency performance evidence
- [ ] Add deterministic slow-provider profiling that compares serial and bounded concurrent execution.
- [ ] Assert result equivalence; report p50/p95/p99 and speedup.
- [ ] Keep timing report non-blocking unless the deterministic equivalence invariant fails.

### Task 5: P3 evidence gate
- [ ] Add a repeated-call cold/warm profiling harness and explicit `material_benefit_fraction` policy.
- [ ] Emit `implement_daemon=true|false` from measurements rather than preference.
- [ ] If true, implement and validate the daemon/hot cache in its own PR; if false, record the measured deferral because the audit explicitly requires that outcome.

### Task 6: CI integration
- [ ] Add the checked-in baseline regression check to CI.
- [ ] Preserve the existing benchmark summary for automation consumers.
- [ ] Publish the non-blocking performance/P3 profile in logs/artifacts.
- [ ] Run the full platform matrix.
