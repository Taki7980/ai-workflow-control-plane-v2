# Core contracts and safe setup

This document records the audit-driven compatibility and safety contracts added after the deterministic/provider/concurrency/state stages.

## Setup

`ai-workflow setup` targets an existing project by default. A missing root is an error unless `--create` is supplied explicitly. This prevents a typo in `--root` from silently creating and initializing an unintended directory.

Setup uses `auto` indexing: it builds a full index when no state exists, then uses incremental indexing on later runs. `--no-index` skips indexing for very large repositories or provisioning workflows. The strict `bootstrap` compatibility command still creates a fresh scaffold and performs a full index.

`.ai/PROJECT` contains `.` rather than an absolute checkout path. Checkout location remains diagnostic metadata, not project identity.

## Context identities

`ContextItem.dedupe_key` is a BLAKE2 content digest over canonical whitespace. Dedupe structures no longer retain arbitrarily long source text as set keys.

## Selector complexity

The facility-location selector bounds its working candidate set through `context.selector.max_selector_candidates` (default 200). Mandatory structural evidence is retained first; remaining candidates are ranked deterministically before the bounded selector executes.

## Token estimation

`TokenEstimator` is a protocol. The dependency-free default remains a character-based approximation and is deliberately described as an estimate. Provider integrations may inject a tokenizer-specific estimator without changing the core budget API.

## Generated-state writes

Generated control-plane files use a sibling temporary file, `fsync`, and `os.replace`. A failed replacement leaves the previous target intact.

## Doctor contract

Doctor JSON now includes `schema_version`, `core_ok`, `optional_capabilities`, and documented exit codes. `--strict` keeps the existing behavior: exit 0 when the core control plane is healthy and exit 1 otherwise. Optional providers are reported separately from core readiness.
