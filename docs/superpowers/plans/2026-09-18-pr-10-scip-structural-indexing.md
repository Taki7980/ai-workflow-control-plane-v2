# SCIP Structural Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional compiler-backed SCIP structural retrieval for Python, TypeScript/JavaScript, Java, and Go without replacing CRG or the dependency-free lightweight index.

**Architecture:** Add a focused `scip.py` adapter that owns language detection, central index state, provenance validation, SCIP JSON conversion, and explicit index generation. Wire it into the existing WorkflowEngine structural-expansion seam as a fallback/alternative provider. Extend the existing benchmark provider-family ablation instead of adding a new benchmark system.

**Tech Stack:** Python standard library, existing ContextItem/ProviderResult/repository fingerprint contracts, external SCIP CLI/indexers.

**Spec:** `docs/research/2026-09-18-pr-10-scip-structural-indexing.md`

## Global Constraints

- [ ] No new runtime dependency.
- [ ] No protobuf vendoring.
- [ ] No shell execution.
- [ ] No silent index generation during retrieval.
- [ ] Existing CRG behavior remains primary when it returns valid structural evidence.
- [ ] SCIP failure must degrade to existing retrieval.
- [ ] Generated state stays centralized below `ai-workspace/scip/`.
- [ ] CI coverage, Ruff, mypy, security, package, platform, and benchmark gates remain unchanged.

## Task 1 — RED: define SCIP contracts

- [ ] Add tests for Python/TS-JS/Java/Go indexer detection.
- [ ] Add tests for camelCase/snake_case SCIP JSON occurrence parsing.
- [ ] Add tests that stale/missing SCIP state fails closed.
- [ ] Add WorkflowEngine tests for CRG-first and SCIP fallback behavior.
- [ ] Add sufficiency test proving any trusted `structural_valid` item can satisfy requested structural patterns.
- [ ] Run targeted tests and confirm expected failures.

## Task 2 — Implement central SCIP adapter

- [ ] Add `ai_workflow/scip.py`.
- [ ] Define central per-repository state paths.
- [ ] Detect one supported language adapter deterministically.
- [ ] Run language indexer only through explicit sync.
- [ ] Move/copy generated `index.scip` into central state.
- [ ] Write manifest with index SHA, Git HEAD, repository fingerprint, language/indexer identity.
- [ ] Validate manifest before retrieval.
- [ ] Use `scip print --json` to consume indexes and map occurrences to ContextItem.

## Task 3 — Integrate structural fallback

- [ ] Add SCIP readiness to ProviderStatus without breaking positional callers.
- [ ] Generalize structural sufficiency from a hard-coded CRG source name to the existing `structural_valid` evidence contract.
- [ ] Keep CRG first when ready.
- [ ] Invoke SCIP only when structural evidence remains incomplete.
- [ ] Preserve current source fallback when neither provider yields valid evidence.
- [ ] Record SCIP attempt/failure in existing diagnostics.

## Task 4 — Explicit CLI control

- [ ] Add a thin `scip status` / `scip sync` command surface without expanding the monolithic CLI unnecessarily.
- [ ] Auto mode consumes fresh indexes only.
- [ ] Off mode disables SCIP.
- [ ] Sync reports unsupported/missing indexer cases without corrupting existing state.

## Task 5 — Benchmark evidence

- [ ] Add `base_scip` to the existing ablation profile family.
- [ ] Ensure base-only/semantic/structural profiles isolate SCIP correctly.
- [ ] Add deterministic tests for profile configuration.
- [ ] Document that real lift claims require frozen external corpora/indexes; fixture tests prove integration, not general superiority.

## Task 6 — Verify and open PR

- [ ] Run targeted tests.
- [ ] Run full unit suite.
- [ ] Run Ruff whole repository.
- [ ] Run mypy whole package.
- [ ] Verify CI Security, Tests, and CodeQL.
- [ ] Update PR body with actual verification evidence.
- [ ] Mark ready only after all required checks are green.
