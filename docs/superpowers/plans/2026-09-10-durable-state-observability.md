# Durable State and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put durable memory behind a transactional store and make retrieval telemetry privacy-aware and exportable without changing core dependencies.

**Architecture:** Define a `MemoryStore` protocol with SQLite as the default durable backend and JSONL import/export compatibility. Add a telemetry sink protocol, deterministic redaction/retention before persistence, and an optional OTLP HTTP sink that uses stdlib networking and fails open without breaking workflow execution.

**Tech Stack:** Python 3.10+ stdlib `sqlite3`, `urllib`, JSON, unittest.

**Spec:** Technical Audit and Improvement Plan — PR E.

## Global Constraints

- Existing JSONL memory must be migratable and exportable.
- SQLite writes are transactional and WAL-enabled with a busy timeout.
- Search ordering and stale-file semantics remain compatible.
- Task text is disabled by default in persisted telemetry.
- Telemetry exporter failure must never fail retrieval.

---

### Task 1: MemoryStore and SQLite adapter

**Files:** Create `ai_workflow/memory_store.py`; Modify `ai_workflow/memory.py`; Test migration, rollback, concurrent writes, stale references.

- [ ] Define `MemoryStore` protocol and `SQLiteMemoryStore`.
- [ ] Create schema with record JSON plus searchable scalar fields and transactional insert/delete/list operations.
- [ ] Add one-time idempotent JSONL import and explicit JSONL export.
- [ ] Keep existing `add_memory`, `search_memory`, `list_memories`, `prune_stale` function signatures as compatibility facades.
- [ ] Prove concurrent writes do not corrupt the store and rollback leaves no partial record.

### Task 2: Telemetry privacy, retention, sinks

**Files:** Modify `ai_workflow/telemetry.py`, `ai_workflow/config.py`; Test `tests/test_telemetry.py`.

- [ ] Add telemetry config for `include_task_text=false`, `retention_days`, `max_trace_files`, and optional OTLP endpoint/headers-env.
- [ ] Redact task text before persistence unless explicitly enabled; store a SHA-256 task fingerprint for correlation.
- [ ] Prune expired/excess local trace files after successful writes.
- [ ] Define `TelemetrySink` protocol and local JSON sink.
- [ ] Add optional OTLP-like JSON HTTP sink using `urllib.request`, with timeout and swallowed exporter errors recorded only as local metadata.

### Task 3: Verification and docs

**Files:** Create `docs/state-and-telemetry.md`; update migration documentation.

- [ ] Test JSONL-to-SQLite migration and export round trip.
- [ ] Test stale-file filtering, pruning, concurrent insertions, redaction, retention, exporter failure.
- [ ] Run full unit suite, index, strict doctor, and benchmark smoke gate.
