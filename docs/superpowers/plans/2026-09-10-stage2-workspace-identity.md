# Stage 2 Workspace Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden multi-repo registry boundaries, add repository-management CLI commands, and provide deterministic per-repository plus aggregate workspace fingerprints.

**Architecture:** Keep repository discovery/persistence in `repository_registry.py`, reuse `path_policy.resolve_within_root()` for confinement, keep activation in `workspace.py`, and extend `workspace_state.py` without breaking the existing single-root fingerprint API. CLI only orchestrates those APIs.

**Tech Stack:** Python 3.10+, standard library only, unittest, existing atomic JSON utilities.

**Spec:** `docs/superpowers/specs/2026-09-10-stage2-workspace-identity-design.md`

## Global Constraints
- Python 3.10+.
- No new runtime dependency.
- Raw remote URLs/credentials must never be persisted.
- Registry-controlled paths must remain inside the workspace root.
- Existing `workspace.roots` and `workspace_fingerprint()` behavior remain compatible.
- New repositories remain excluded until explicitly accepted.

---

### Task 1: Registry security and management API
**Files:** Modify `ai_workflow/repository_registry.py`; test `tests/test_repository_registry.py`.

- [ ] Add failing tests proving persisted registry JSON contains no raw/tokenized remote URL, malformed/version-mismatched registries fail closed, refresh preserves unchanged inclusion and resets inclusion when remote identity changes, and selectors fail on ambiguity.
- [ ] Replace `asdict()` persistence with an explicit credential-free payload and deterministic `repository_id`.
- [ ] Add `load_registry`, `refresh_registry`, `set_repository_included`, and `registry_summary` using atomic JSON writes.
- [ ] Run `python -m unittest tests.test_repository_registry -v`.

### Task 2: Registry path confinement
**Files:** Modify `ai_workflow/workspace.py`; test `tests/test_repository_registry.py`.

- [ ] Add traversal, absolute-path, symlink-escape, duplicate, and non-Git activation tests.
- [ ] Route registry relative paths through `resolve_within_root()` and ignore invalid/unsafe entries; keep legacy `workspace.roots` behavior unchanged.
- [ ] Run `python -m unittest tests.test_repository_registry -v`.

### Task 3: Repository and aggregate workspace state
**Files:** Modify `ai_workflow/workspace_state.py`; test `tests/test_workspace_state.py`.

- [ ] Add tests for stable repository IDs/fingerprints, dirty-state changes, aggregate checkout-path independence, deterministic ordering, and aggregate changes when one repo changes.
- [ ] Add repository snapshots containing stable identity, Git HEAD/ref, dirty digest, index digest, and fingerprint.
- [ ] Add aggregate workspace snapshot/fingerprint over active roots without absolute paths in the hashed payload.
- [ ] Preserve existing `workspace_fingerprint()` API.
- [ ] Run `python -m unittest tests.test_workspace_state -v`.

### Task 4: Repository management CLI
**Files:** Modify `ai_workflow/cli.py`; test `tests/test_cli.py`.

- [ ] Add CLI tests for `repos list`, `repos refresh`, `repos include`, and `repos exclude`, including JSON output and no-write failure behavior.
- [ ] Add command handlers and parser wiring with selectors by relative path/repository ID/remote identity/unique name.
- [ ] Ensure refresh depth defaults from config and inclusion changes are explicit.
- [ ] Run `python -m unittest tests.test_cli -v`.

### Task 5: Verification and PR
**Files:** Update docs only if command behavior differs from the spec.

- [ ] Run full `python -m unittest discover -s tests -v` in CI.
- [ ] Require quality, benchmark regression, package smoke, and compatibility matrix to pass.
- [ ] Open PR from `research/stage2-workspace-identity` to `main` with scope, security guarantees, and verification evidence.