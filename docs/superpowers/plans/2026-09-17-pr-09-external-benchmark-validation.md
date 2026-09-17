# PR-09 External Benchmark Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible, non-vendored adapters for Agent Retrieval Bench and CORE-Bench inputs plus cross-corpus validation/reporting, without fabricating missing span labels or repository snapshot identities.

**Architecture:** Reuse the existing corpus-v2 document and benchmark protocol. External file-level datasets are normalized into schema-v1 benchmark cases inside corpus-v2 documents; schema-v2 remains reserved for sources that actually provide span/content-manifest evidence. Add one focused adapter module and CLI import/report commands, with source metadata preserved and no network dependency at runtime.

**Tech Stack:** Python 3.11+, stdlib JSON/JSONL, existing `benchmark_corpus` / `benchmark_protocol`, argparse CLI, unittest, Ruff, mypy.

**Spec:** `docs/research/2026-09-11-benchmark-corpus-v2-stage9.md`

## Global Constraints

- Do not vendor upstream benchmark datasets.
- Do not invent line/span labels or content-manifest hashes that upstream data does not provide.
- Preserve upstream source URL/license statements in every generated corpus document.
- External import must be deterministic and offline once source files are present locally.
- Existing internal benchmark behavior and regression gates must remain unchanged.
- File-level imported cases use benchmark case schema version 1; corpus document stays schema version 2.
- PR tracks I-033 through I-036 only.

---

### Task 1: External adapter contracts

**Files:**
- Create: `ai_workflow/benchmark_external.py`
- Test: `tests/test_benchmark_external.py`

**Interfaces:**
- Produces: `adapt_agent_retrieval_bench(records, *, corpus_id, source_url, license_statement, split, repository_paths=None, languages=None) -> dict[str, Any]`
- Produces: `adapt_core_bench(queries, qrels, corpus, *, repository_id, base_commit, corpus_id, source_url, license_statement, split, repository_path='.', language='unknown') -> dict[str, Any]`
- Produces: `load_jsonl(path: Path) -> list[dict[str, Any]]`

- [ ] Write failing tests for ARB task/gold mapping, deterministic task text, provenance, repository-path/language overrides, and fail-closed malformed records.
- [ ] Run the focused test and confirm RED because `benchmark_external` does not exist.
- [ ] Implement the minimum ARB adapter and JSONL loader.
- [ ] Run focused tests to GREEN.
- [ ] Add failing CORE-Bench tests using `queries.jsonl`/`qrels.jsonl`/`corpus.jsonl`-style records and flexible common key aliases.
- [ ] Implement deterministic query-to-qrels-to-file mapping with duplicate removal and fail-closed missing qrels/corpus references.
- [ ] Run focused tests to GREEN.

### Task 2: Cross-corpus external validation report

**Files:**
- Modify: `ai_workflow/benchmark_external.py`
- Test: `tests/test_benchmark_external.py`

**Interfaces:**
- Produces: `external_validation_report(documents, *, required_sources=('agent-retrieval-bench','core-bench'), minimum_languages=4) -> dict[str, Any]`

- [ ] Write failing tests for source coverage, case/repository/language aggregation, duplicate corpus IDs, and readiness blockers.
- [ ] Verify RED.
- [ ] Implement report generation using existing `corpus_summary()` validation.
- [ ] Verify GREEN.

### Task 3: CLI import/report surface

**Files:**
- Modify: `ai_workflow/cli.py`
- Test: `tests/test_benchmark_external_cli.py`

**Interfaces:**
- Adds: `ai-workflow benchmark-corpus import-arb`
- Adds: `ai-workflow benchmark-corpus import-core`
- Adds: `ai-workflow benchmark-corpus external-report`

- [ ] Write parser/command tests first.
- [ ] Verify RED because commands do not exist.
- [ ] Wire local-file-only import and report commands.
- [ ] Write outputs through existing atomic JSON helper.
- [ ] Verify focused tests GREEN.

### Task 4: Source registry and research documentation

**Files:**
- Modify: `benchmarks/corpus-v2/sources.json`
- Create: `docs/research/2026-09-17-pr-09-external-benchmark-validation.md`

**Interfaces:**
- Documents exact upstream formats supported and explicit non-claims.

- [ ] Update ARB source to current released repository/download model.
- [ ] Add CORE-Bench dataset/evaluation repository URLs and Level-2/Level-3 JSONL layout.
- [ ] Document ContextBench as future span/trajectory evidence, not silently treated as implemented.
- [ ] Document that external adapters do not download data and do not infer redistribution rights.

### Task 5: Verification

**Files:** none beyond fixes required by verification.

- [ ] Run focused external benchmark tests.
- [ ] Run whole repository Ruff.
- [ ] Run whole-package mypy.
- [ ] Run unit suite and branch coverage floor.
- [ ] Run existing benchmark regression and repository hygiene gates.
- [ ] Confirm CRG/install/security workflows remain green in GitHub Actions.
- [ ] Review the final diff for scope creep and ensure no upstream dataset content is vendored.
