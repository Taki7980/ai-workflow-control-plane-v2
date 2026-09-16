# Repository Hygiene and Pollution Prevention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent AI Workflow runtime, machine-local, credential, build, test, editor, and generated artifacts from polluting source repositories while preserving deliberate configuration/templates and historical engineering provenance.

**Architecture:** Use two Git-native layers. Project-wide artifact classes that every clone should ignore are encoded in the repository `.gitignore`; machine-local AI Workflow state in a managed Git workspace is additionally protected with an idempotent block in Git's repository-local `$GIT_COMMON_DIR/info/exclude`. A dependency-free hygiene validator enforces the contract in CI and doctor surfaces effective ignore coverage without deleting user data.

**Tech Stack:** Python 3.10+, Git CLI, unittest, GitHub Actions, existing atomic I/O helpers.

**Spec:** PR-04 / I-013–I-016 from the hardening tracker, grounded in `AI Workflow v2 Repository Deep Research and Engineering Assessment` (2026-09-15), Git 2.55 ignore semantics, and the OpenSSF OSPS Baseline 2026-08-28.

## Global Constraints

- Defensive cleanup only: do not mass-delete docs, wrappers, templates, benchmark baselines, or `ai-workspace/` contract material.
- Do not rewrite Git history.
- Do not auto-run destructive `git clean`, `git rm`, or force-push operations.
- Preserve zero mandatory runtime Python dependencies.
- Preserve single-repo, non-Git workspace, nested-repo, and Git worktree behavior.
- Do not modify user-tracked `.gitignore` during `ai-workflow setup`; use repository-local Git excludes for machine-local state.
- Preserve existing content in `.git/info/exclude` and make AI Workflow's managed block idempotent.
- CI must fail closed if forbidden generated/machine-local artifacts become tracked.
- TDD: every production behavior must be preceded by a regression test that fails for the expected reason.
- Do not merge PR-04 automatically.

---

### Task 1: Expand project-wide ignore policy — I-013

**Files:**
- Modify: `.gitignore`
- Test: `tests/test_repository_hygiene.py`

**Interfaces:**
- Produces an effective ignore contract for Python build/test state, OS/editor metadata, local credentials, legacy provider state, AI Workflow runtime state, and machine-local repository discovery.

- [ ] Add a test that invokes Git `check-ignore --no-index` against representative paths and proves the current `.gitignore` misses required categories.
- [ ] Cover Python packaging/build outputs: `build/`, `dist/`, `*.egg-info/`, `.eggs/`.
- [ ] Cover test/quality state: `.coverage*`, `coverage.xml`, `htmlcov/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`, `junit*.xml`.
- [ ] Cover OS/editor metadata: `.DS_Store`, `Thumbs.db`, `.idea/`, `.vscode/`.
- [ ] Cover local credentials: `.env`, `.env.*`, while explicitly allowing `.env.example`; block `*.pem`, `*.key`, `credentials/`, `secrets/`.
- [ ] Cover AI Workflow machine-local registry: `ai-workspace/config/repositories.json`.
- [ ] Preserve `ai-workspace/generated/.gitkeep` and `ai-workspace/memory/README.md`.
- [ ] Run the focused ignore-policy tests.

### Task 2: Git-local excludes for managed projects — I-014

**Files:**
- Create: `ai_workflow/repository_hygiene.py`
- Modify: `ai_workflow/bootstrap.py`
- Test: `tests/test_repository_hygiene.py`
- Test: `tests/test_setup_research.py`

**Interfaces:**
- Produce: `install_local_excludes(root: Path) -> dict`
- Produce: `local_exclude_health(root: Path) -> dict`
- Managed block markers:
  - `# >>> ai-workflow local state >>>`
  - `# <<< ai-workflow local state <<<`

- [ ] Add a real-Git test with pre-existing `.git/info/exclude` content.
- [ ] Assert setup preserves the existing content and appends exactly one AI Workflow managed block.
- [ ] Rerun setup and assert the block is not duplicated.
- [ ] Use `git rev-parse --git-common-dir` to locate the repository-local exclude file, resolving relative output against the worktree.
- [ ] Install anchored rules only for machine-local state: repository registry, generated indexes/traces, central indexes, managed CRG state, and runtime memory.
- [ ] Do not exclude team-shareable `control-plane.json`, `agents/`, `state/PROJECT`, templates, or docs.
- [ ] Non-Git control roots must return a deterministic skipped/not-applicable result without filesystem side effects.
- [ ] Wire the installer into setup before runtime indexes/graphs are built.
- [ ] Return hygiene status from setup without breaking existing fields.

### Task 3: Tracked-artifact hygiene validator — I-015

**Files:**
- Extend: `ai_workflow/repository_hygiene.py`
- Create: `scripts/check_repository_hygiene.py`
- Test: `tests/test_repository_hygiene.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produce: `repository_hygiene(root: Path) -> dict`
- CLI exits 0 only when the tracked tree contains no forbidden machine-local/generated artifacts.
- CLI supports human-readable output and `--json`.

- [ ] Add a temp-repo test that force-adds an ignored `.env` file and assert the validator reports it.
- [ ] Add a temp-repo test that force-adds `ai-workspace/config/repositories.json` and assert the validator reports it even if ignore rules are later weakened.
- [ ] Add positive tests for deliberate tracked exceptions: `.env.example`, `ai-workspace/generated/.gitkeep`, and `ai-workspace/memory/README.md`.
- [ ] Query tracked paths with `git ls-files -z`; never walk `.git` directly.
- [ ] Query ignored-but-tracked paths with `git ls-files -ci --exclude-standard -z`.
- [ ] Fail on explicit forbidden path classes independently of `.gitignore` so deleting an ignore line cannot bypass CI.
- [ ] Add a quality-job step: `python scripts/check_repository_hygiene.py --root .`.
- [ ] Do not enforce arbitrary source-file size limits; report cleanup should remain evidence-based rather than destructive.

### Task 4: Doctor hygiene contract and conservative cleanup proof — I-016

**Files:**
- Modify: `ai_workflow/doctor.py`
- Test: `tests/test_repository_hygiene.py`
- Test: `tests/test_doctor.py`
- Update: `README.md`

**Interfaces:**
- Doctor adds `repository_hygiene` with `applicable`, `local_state_ignored`, `tracked_forbidden`, and remediation.
- Strict health fails only when a Git control workspace can expose/track AI Workflow machine-local state or already contains forbidden tracked artifacts.

- [ ] Add a doctor test for a Git workspace before local excludes are installed: hygiene unhealthy.
- [ ] Run setup, then assert doctor hygiene becomes healthy.
- [ ] Force-track a forbidden runtime artifact and assert strict doctor fails with a non-destructive remediation.
- [ ] Non-Git outer workspaces remain not-applicable rather than failing.
- [ ] Document that setup uses `.git/info/exclude` for machine-local state and does not edit the user's tracked `.gitignore`.
- [ ] Document the safe cleanup rule: preview with `git clean -ndX`; never automate destructive cleanup.
- [ ] Verify the current tracked tree contains no forbidden artifacts; delete nothing unless this check identifies an objectively generated/machine-local tracked file.
- [ ] Run full compatibility, quality, benchmark, package, CRG, and security workflows.
- [ ] Review changed files for PR-05+ scope creep.
- [ ] Open PR-04 ready for review and leave it unmerged.
