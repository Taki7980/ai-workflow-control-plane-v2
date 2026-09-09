# Incremental Index Fast Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make incremental indexing avoid hashing unchanged files while retaining an opt-in strict verification mode.

**Architecture:** Extend index-state file entries with `size` and `mtime_ns`. Normal incremental mode reuses the previous digest when both stat values match; changed candidates are hashed. Strict mode hashes every source file and verifies content identity.

**Tech Stack:** Python 3.10+ stdlib filesystem APIs and existing atomic index writer.

**Spec:** Technical Audit and Improvement Plan — P1 Faster incremental indexing.

## Global Constraints

- Existing version-2 state remains readable.
- Normal incremental output must match full indexing for the same content.
- Strict verification must detect content changes even when metadata is preserved deliberately.
- No new dependency.

---

### Task 1: State metadata and fast path

**Files:** Modify `ai_workflow/indexer.py`; Test `tests/test_indexer.py` and new `tests/test_incremental_index.py`.

- [ ] Add failing tests that patch `sha256` and prove unchanged stat-matched files are not hashed.
- [ ] Add failing tests proving changed size/mtime candidates are hashed and reparsed.
- [ ] Store `sha256`, `size`, and `mtime_ns` in state during full and incremental builds.
- [ ] Preserve compatibility for legacy entries containing only `sha256` by hashing once and upgrading metadata.

### Task 2: Strict verification mode

**Files:** Modify `ai_workflow/indexer.py`, `ai_workflow/cli.py`; Test CLI/indexer behavior.

- [ ] Add `incremental_indexes(root, strict_hash=False)`.
- [ ] In strict mode hash all current source files and compare digests regardless of stat match.
- [ ] Add `ai-workflow index --incremental --strict-hash` without changing default full-index behavior.
- [ ] Verify deleted files are removed in both modes.

### Task 3: Verification

- [ ] Run full unit suite.
- [ ] Run full index then incremental index twice and verify the second normal incremental run reports all files skipped.
- [ ] Run strict incremental verification and benchmark smoke gate.
