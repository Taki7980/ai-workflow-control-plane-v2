# Concurrent Retrieval Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace serial broker fan-out with a bounded asynchronous retrieval engine that preserves deterministic ranking and the existing synchronous API.

**Architecture:** Keep the project as one dependency-free Python package. Add a small scheduler that runs blocking adapters through `asyncio.to_thread`, enforces a semaphore plus one global deadline, and returns results in stable provider order. Add `WorkflowEngine` as the sequencing layer; keep `adaptive_broker.gather_detailed()` as a compatibility wrapper.

**Tech Stack:** Python 3.10+ stdlib `asyncio`, existing provider contracts, unittest.

**Spec:** Technical Audit and Improvement Plan — PR C.

## Global Constraints

- Preserve ranking/selection semantics for identical provider results.
- No mandatory dependency additions.
- Max concurrency and global deadline must be configurable and bounded.
- Provider result ordering must be deterministic regardless of completion order.
- Existing synchronous broker callers remain supported.

---

### Task 1: Scheduler

**Files:** Create `ai_workflow/retrieval_scheduler.py`; Test `tests/test_retrieval_scheduler.py`.

**Interfaces:** Produces `ScheduledCall`, `SchedulerResult`, and `BoundedRetrievalScheduler.run(calls, deadline_seconds)`.

- [ ] Write tests for max concurrency, global deadline, timeout result, and stable result order.
- [ ] Run `python -m unittest tests.test_retrieval_scheduler -v` and confirm red.
- [ ] Implement semaphore-bounded `asyncio.to_thread` execution using monotonic remaining-deadline calculations and `asyncio.wait_for`.
- [ ] Re-run scheduler tests and confirm green.

### Task 2: Workflow engine and adapters

**Files:** Create `ai_workflow/workflow_engine.py`; Modify `ai_workflow/adaptive_broker.py`; Test `tests/test_workflow_engine.py`, `tests/test_adaptive_broker.py`.

**Interfaces:** Produces `WorkflowEngine.gather_detailed_async(...)` and `gather_detailed_async(...)`; synchronous `gather_detailed(...)` remains compatible.

- [ ] Add characterisation tests comparing deterministic old/new ordered context for fixed provider outputs.
- [ ] Add tests proving multiple workspace roots and independent specialist providers overlap in elapsed time.
- [ ] Implement local workspace, semantic, and external provider scheduled calls with deterministic labels.
- [ ] Keep ranking, sufficiency, selector, diagnostics, and orchestration construction in the engine without semantic changes.
- [ ] Route `adaptive_broker` public APIs through the engine.

### Task 3: Configuration and documentation

**Files:** Modify `ai_workflow/config.py`; Create `docs/concurrency.md`; update tests.

**Interfaces:** Add `execution.retrieval_scheduler.max_concurrency` and `global_deadline_seconds` with safe defaults.

- [ ] Validate positive concurrency and deadline values.
- [ ] Document cancellation limitations of blocking local adapters and provider-local timeouts.
- [ ] Run full unit suite, index, strict doctor, and benchmark smoke gate.
