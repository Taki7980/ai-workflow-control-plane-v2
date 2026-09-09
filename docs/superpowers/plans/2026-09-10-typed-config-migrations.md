# Typed Configuration and Migration Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an immutable typed configuration boundary and explicit schema migration path while retaining JSON input and backwards-compatible dict consumers.

**Architecture:** Parse raw JSON through a migration function, validate the migrated v2 shape, then expose a frozen `ControlPlaneConfig` mapping backed by recursively immutable mappings/tuples. Existing `load_config()` continues returning a normal dict for compatibility; new code can use `load_typed_config()` and `parse_typed_config()`.

**Tech Stack:** Python 3.10+ stdlib `dataclasses`, `collections.abc`, `types.MappingProxyType`, JSON, unittest.

**Spec:** Technical Audit and Improvement Plan — P2 Typed configuration + migration layer.

## Global Constraints

- Current v2 JSON remains valid without edits.
- Unknown fields must survive parse -> typed -> `to_dict()` round trips.
- Config migration is explicit, deterministic, and side-effect free.
- Existing `load_config(root) -> dict` callers remain supported.
- No mandatory dependency additions.

---

### Task 1: Immutable typed wrapper

**Files:** Create `ai_workflow/typed_config.py`; Test `tests/test_typed_config.py`.

- [ ] Write failing tests proving recursive immutability, Mapping compatibility, attribute access for common sections, unknown-field preservation, and deep `to_dict()` round trip.
- [ ] Implement recursive freeze/thaw helpers and frozen `ControlPlaneConfig` implementing `Mapping[str, Any]`.
- [ ] Provide typed convenience properties for `context`, `execution`, `workspace`, `memory`, `budgets`, and `models` while retaining `config["..."]`/`.get(...)` behavior.

### Task 2: Version migrations

**Files:** Modify `ai_workflow/config.py`; Test migration fixtures.

- [ ] Add pure `migrate_config(data) -> dict` with a migration registry and clear unsupported-future-version error.
- [ ] Support legacy missing-version/v1 inputs by deep-merging them over v2 defaults and setting `version=2`, preserving unknown keys.
- [ ] Validate only after migration.
- [ ] Add `parse_typed_config(data)` and `load_typed_config(root)`; keep `load_config(root)` returning a detached mutable dict.

### Task 3: Migration UX and docs

**Files:** Create `docs/configuration-migrations.md`; Modify `MIGRATION-v2.md` if required.

- [ ] Document schema version semantics, unknown-field behavior, typed API, and future-version refusal.
- [ ] Add tests for current v2 round trip, v1/missing-version upgrade, unknown fields, caller mutation isolation, and unsupported v3 refusal.
- [ ] Run the full unit suite, index, strict doctor, and benchmark smoke gate.
