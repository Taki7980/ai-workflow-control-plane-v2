# V2.2 Agentic Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mathematically budgeted context assembly, workspace-state fingerprints, explicit evidence states, and a CRG-to-Superpowers orchestration contract to the existing V2.1 adaptive retrieval branch.

**Architecture:** Keep V2.1 routing, providers, RRF and MMR. Add focused dependency-free modules after retrieval fusion: `context_selection.py` for relevance/facility-location assembly, `workspace_state.py` for content-bound fingerprints, and `orchestration.py` for structural complexity and conserved execution budgets. `adaptive_broker.py` coordinates these modules and exposes diagnostics; CLI/benchmark surface the new contract.

**Tech Stack:** Python 3.10+ standard library only; existing ai_workflow modules; optional CRG/Superpowers remain external integrations.

**Spec:** `docs/superpowers/specs/2026-09-07-v22-agentic-orchestration-design.md`

## Global Constraints

- No mandatory new runtime dependency.
- Deterministic high-risk routing remains authoritative.
- Superpowers and CRG are coordinated but not reimplemented.
- Hard lane context ceilings are never exceeded.
- Statistical/calibration claims require representative labeled data and are out of scope.
- Missing optional providers must degrade safely.

---

### Task 1: Budgeted context selector

**Files:**
- Create: `ai_workflow/context_selection.py`
- Create: `tests/test_context_selection.py`

**Interfaces:**
- Produces: `select_context(query, items, char_budget, config, mandatory_sources=()) -> tuple[list[ContextItem], dict]`

- [ ] Write tests for tight-budget relevance-first selection, normal-budget coverage selection, mandatory evidence, determinism, dedupe, and hard budget enforcement.
- [ ] Run tests and confirm they fail because the module does not exist.
- [ ] Implement normalized relevance, token Jaccard, facility-location marginal gain, and lazy greedy gain-per-char selection.
- [ ] Run focused tests and full suite.

### Task 2: Workspace-state fingerprint

**Files:**
- Create: `ai_workflow/workspace_state.py`
- Create: `tests/test_workspace_state.py`

**Interfaces:**
- Produces: `workspace_fingerprint(root, changed_files=None) -> dict`

- [ ] Write tests showing fingerprint stability for unchanged state and change after source mutation.
- [ ] Verify tests fail before implementation.
- [ ] Implement stable SHA-256 over resolved root, Git HEAD when available, index-state bytes and changed-file content hashes.
- [ ] Run focused tests and full suite.

### Task 3: CRG-Superpowers orchestration contract

**Files:**
- Create: `ai_workflow/orchestration.py`
- Create: `tests/test_orchestration.py`

**Interfaces:**
- Produces: `build_orchestration_contract(decision, retrieval_diagnostics, changed_files, workspace_count, providers, config) -> dict`

- [ ] Write tests for Answer, Small, Full structural, and high-risk Full contracts plus component-wise budget conservation.
- [ ] Verify tests fail before implementation.
- [ ] Implement complexity vector, CRG action plan, Superpowers skill sequence, and conserved resource budget.
- [ ] Run focused tests and full suite.

### Task 4: Integrate evidence state and selector

**Files:**
- Modify: `ai_workflow/adaptive_broker.py`
- Modify: `ai-workspace/config/control-plane.json`
- Modify: `ai_workflow/config.py`
- Modify: `tests/test_adaptive_broker.py`

- [ ] Add failing integration tests for `evidence_state`, selector diagnostics, workspace fingerprint, and hard budget.
- [ ] Verify RED.
- [ ] Wire RRF candidates -> evidence state -> budgeted selector; preserve MMR fallback.
- [ ] Add selector config validation.
- [ ] Verify GREEN and full suite.

### Task 5: Surface orchestration contract

**Files:**
- Modify: `ai_workflow/cli.py`
- Modify: `ai_workflow/benchmark.py`
- Modify: `benchmarks/sample-tasks.json`
- Create: `tests/test_v22_benchmark.py`

- [ ] Add tests for contract/evidence-state fields and no-gold abstention metrics.
- [ ] Implement CLI packet fields and benchmark metrics: evidence-state accuracy, abstention accuracy, relevant-pattern density/yield.
- [ ] Add no-gold benchmark cases without weakening existing gold metrics.
- [ ] Run full suite and benchmark smoke gate.

### Task 6: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Create: `docs/research/2026-09-07-v22-research.md`
- Modify: PR #1 body

- [ ] Document formulas, CRG/Superpowers role separation, evidence states and limitations.
- [ ] Run GitHub Actions matrix and benchmark smoke gate on final branch head.
- [ ] Compare branch to main and review diff for accidental scope.
- [ ] Update existing PR #1 with V2.2 summary and final verification evidence.
