# CI and Code Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand AI Workflow's existing CI from selected quality/security boundaries to whole-package static quality, branch-aware coverage, CodeQL, and HIGH/CRITICAL container vulnerability enforcement without weakening existing gates.

**Architecture:** Keep the current Tests and Security workflows. Replace file-list quality checks with repository-level commands driven by `pyproject.toml`, ratchet coverage to branch-aware 80%, add a dedicated pinned CodeQL workflow, and broaden the existing Trivy policy to HIGH+CRITICAL with a reviewed exception file. Existing package, benchmark, CRG, provider-security, secret-scan, and release checks remain unchanged.

**Tech Stack:** Python 3.11+, Ruff 0.16.x, mypy 1.x, coverage.py 7.16.x, GitHub Actions, GitHub CodeQL v3 pinned to commit `faaca9a8f6edddba5725ffe5adefdab6669a2eca`, Trivy 0.74.0.

**Spec:** AI Workflow v2 Repository Deep Research and Engineering Assessment, quality-expansion section (2026-09-15), plus current GitHub secure-use/CodeQL, Ruff, coverage.py and Trivy documentation.

## Global Constraints

- Preserve zero runtime Python dependencies.
- Preserve all current compatibility, package, benchmark, CRG, installation and security jobs.
- Keep all third-party GitHub actions pinned to full immutable commit SHAs.
- Do not enable Ruff `ALL`; use an explicit stable rule set and narrow suppressions.
- Do not suppress mypy errors package-wide to make the gate pass.
- Coverage must use branch measurement and fail below 80%.
- CodeQL must run with least required permissions and upload SARIF through GitHub's supported action.
- Trivy must fail on HIGH and CRITICAL fixed vulnerabilities.
- Any Trivy exception must be explicit, scoped and reviewable; no blanket severity exclusion.
- Do not change branch protection/repository settings in this PR.
- Do not merge automatically.

---

### Task 1: Whole-repository Ruff policy — I-029

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/tests.yml`
- Test: `tests/test_ci_quality_contracts.py`

**Interfaces:**
- `ruff check ai_workflow tests security_tests scripts`
- `[tool.ruff.lint]` owns the stable rule selection.
- Initial blocking correctness families: `E9,F,B,BLE,EXE`. Import sorting and style-only modernization remain measured debt for later cleanup so this PR does not become a mass-format rewrite.
- Narrow per-file ignores are allowed only where the code's trust-boundary behavior intentionally triggers a rule.

- [ ] Add a failing workflow/config contract test proving the current workflow still enumerates files.
- [ ] Add the explicit Ruff configuration to `pyproject.toml`.
- [ ] Replace file-list Ruff CI with one whole-repository command.
- [ ] Run Ruff and fix only correctness/modernisation findings required by the selected rules.
- [ ] Add the smallest justified per-file ignores instead of global ignores when intentional patterns remain.

### Task 2: Whole-package mypy — I-030

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `pyproject.toml` only if narrow typing configuration is required.
- Test: `tests/test_ci_quality_contracts.py`
- Modify: individual `ai_workflow/*.py` files only when mypy exposes real errors.

**Interfaces:**
- CI command is exactly `mypy ai_workflow`.
- Existing `python_version = "3.11"` and `check_untyped_defs = true` remain.
- No package-wide `ignore_errors = true`.

- [ ] Add a failing contract test proving current mypy remains file-list based.
- [ ] Change CI to `mypy ai_workflow`.
- [ ] Run mypy and group failures by root cause.
- [ ] Fix typing issues with local annotations/narrowing/protocol corrections.
- [ ] Use per-module overrides only when required for an external untyped boundary, with a comment explaining why.

### Task 3: Branch-aware coverage ratchet — I-031

**Files:**
- Modify: `.github/workflows/security.yml`
- Test: `tests/test_ci_quality_contracts.py`
- Modify/Create: focused tests under `tests/` where measured branch coverage is below target.

**Interfaces:**
- `coverage run --branch --source=ai_workflow -m unittest discover -s tests -q`
- `coverage report --show-missing --fail-under=80`

- [ ] Add a failing contract test for branch measurement and 80% floor.
- [ ] Enable branch coverage in Security CI.
- [ ] Raise fail-under from 65 to 80.
- [ ] Run measured coverage and identify the largest uncovered branch clusters.
- [ ] Add behavior-focused tests for those branches; do not add no-op coverage padding.
- [ ] Keep the 80% threshold blocking once achieved.

### Task 4: CodeQL + HIGH/CRITICAL container policy — I-032

**Files:**
- Create: `.github/workflows/codeql.yml`
- Modify: `.github/workflows/security.yml`
- Create: `security/trivy-ignore.yaml`
- Test: `tests/test_ci_quality_contracts.py`

**Interfaces:**
- CodeQL action SHA: `faaca9a8f6edddba5725ffe5adefdab6669a2eca`.
- CodeQL language: Python.
- Workflow permissions: `contents: read`, `security-events: write`.
- Trivy severity: `HIGH,CRITICAL`.
- Trivy exception file: `security/trivy-ignore.yaml`.

- [ ] Add failing tests requiring the CodeQL workflow and HIGH+CRITICAL Trivy policy.
- [ ] Add CodeQL init/analyze steps pinned to the exact v3 commit SHA.
- [ ] Keep checkout pinned to the repository's current immutable checkout SHA.
- [ ] Add an explicit Trivy ignore YAML containing no active exceptions by default and documentation comments requiring CVE, scope, rationale and expiry for future entries.
- [ ] Pass the ignore file explicitly with `--ignorefile`.
- [ ] Run the HIGH+CRITICAL scan and inspect any finding before adding an exception.
- [ ] Never suppress an entire severity class.

### Final verification

- [ ] Whole-repository Ruff passes.
- [ ] `mypy ai_workflow` passes.
- [ ] Branch-aware coverage is >=80%.
- [ ] CodeQL workflow succeeds.
- [ ] Trivy HIGH+CRITICAL policy succeeds.
- [ ] Existing Python security, secret scan, CRG contract, benchmark regression, package/install smoke and platform compatibility remain green.
- [ ] Review all suppressions/exceptions for necessity.
- [ ] Review diff for PR-09+ scope creep.
- [ ] Mark PR ready only after exact-head CI is green.
- [ ] Leave PR unmerged for explicit human approval.
