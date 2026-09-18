# Modular Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce monolithic command/import coupling while preserving every existing user-visible CLI and public Python API contract.

**Architecture:** Extract command handlers/parser registration into focused domain modules, introduce curated retrieval/provider/state/evaluation package boundaries, and keep `ai_workflow.cli`, `ai_workflow.entrypoint`, and top-level package exports as compatibility facades.

**Tech Stack:** Python 3.11+, standard library `argparse`, existing package/test stack. No new dependency.

**Spec:** `docs/research/2026-09-18-pr-12-modular-architecture.md`

## Global Constraints

- [ ] No user-visible behavior change.
- [ ] No config/storage schema change.
- [ ] `ai-workflow = ai_workflow.entrypoint:main` remains unchanged.
- [ ] Existing command names and nested subcommands remain unchanged.
- [ ] `ai_workflow.__all__` remains unchanged.
- [ ] Existing top-level module imports remain valid.
- [ ] No new runtime dependency.
- [ ] Full CI/security/benchmark/platform gates remain unchanged.

### Task 1 — RED: freeze compatibility contracts

**Files:**
- Create: `tests/test_modular_architecture.py`
- Modify: `tests/test_cli.py` only if existing coverage cannot express the contract.

- [ ] Assert `ai_workflow.__all__` is unchanged.
- [ ] Assert entrypoint target remains `ai_workflow.entrypoint:main`.
- [ ] Assert the full top-level command set is unchanged.
- [ ] Assert nested command sets for repos/benchmark-corpus/learning/deployment/production/memory are unchanged.
- [ ] Assert representative legacy `ai_workflow.cli.cmd_*` names remain importable.
- [ ] Assert new domain packages import successfully.
- [ ] Run tests and confirm RED only because new packages/modules do not exist.

### Task 2 — establish domain package APIs

**Files:**
- Create: `ai_workflow/retrieval/__init__.py`
- Create: `ai_workflow/provider/__init__.py`
- Create: `ai_workflow/state/__init__.py`
- Create: `ai_workflow/evaluation/__init__.py`

**Interfaces:**
- `retrieval`: WorkflowEngine, retrieval intent/sufficiency/core retrieval entry points.
- `provider`: ProviderStatus/detection/model/execution-provider boundaries.
- `state`: run provenance, telemetry, workspace/run-journal state.
- `evaluation`: benchmark/ablation/statistics/protocol entry points.

- [ ] Export only existing stable implementation objects.
- [ ] Do not duplicate implementation.
- [ ] Add explicit `__all__`.
- [ ] Verify imports are cycle-free.

### Task 3 — split command handlers

**Files:**
- Create: `ai_workflow/commands/__init__.py`
- Create: `ai_workflow/commands/common.py`
- Create: `ai_workflow/commands/workspace.py`
- Create: `ai_workflow/commands/memory.py`
- Create: `ai_workflow/commands/evaluation.py`
- Create: `ai_workflow/commands/learning.py`
- Create: `ai_workflow/commands/deployment.py`
- Create: `ai_workflow/commands/production.py`

- [ ] Move command-handler implementation without changing signatures/behavior.
- [ ] Shared helpers live only in `common.py`.
- [ ] Domain modules import through the new domain packages where practical.
- [ ] Keep each command family independently importable/testable.

### Task 4 — split parser construction

**Files:**
- Create: `ai_workflow/commands/parser.py`
- Modify: `ai_workflow/cli.py`

- [ ] Move parser construction into focused registration helpers.
- [ ] `build_parser()` continues returning the same parser contract.
- [ ] `cli.py` re-exports all legacy command handler names.
- [ ] `cli.main()` remains behavior-compatible.

### Task 5 — compatibility facade

**Files:**
- Modify: `ai_workflow/cli.py`
- Verify: `ai_workflow/entrypoint.py`
- Verify: `ai_workflow/__init__.py`

- [ ] Preserve legacy imports.
- [ ] Preserve console entrypoint.
- [ ] Preserve package `__all__`.
- [ ] Add no deprecation warning because behavior remains supported.

### Task 6 — architecture/research documentation

**Files:**
- Create/modify: architecture documentation describing preferred package boundaries.
- Document old import paths as supported compatibility facades.
- Document new internal dependency direction.

### Task 7 — final verification

- [ ] Run targeted modular-architecture tests.
- [ ] Run full unit suite.
- [ ] Run compile.
- [ ] Run repository hygiene.
- [ ] Run Ruff whole repository.
- [ ] Run mypy whole package.
- [ ] Run coverage >=80%.
- [ ] Run benchmark regression.
- [ ] Run CRG contract.
- [ ] Run package/Docker/install/portable/platform matrix.
- [ ] Run Security and CodeQL.
- [ ] Open/mark PR ready only when all required checks are green.
