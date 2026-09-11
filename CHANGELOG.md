# Changelog

All notable repository changes are summarized here. The project follows semantic versioning for package releases.

## Unreleased

### Added

- Stage-8 production rollout hardening with an opt-in same-host SQLite WAL evidence mirror and reconciliation, crash-recoverable local rollout locks, task-cluster bootstrap diagnostics, low-cardinality observability exports, and signed privacy-minimized rollback incident bundles.
- Stage-7 controlled contextual-policy deployment with signed generation-checked rollout state, randomized 1%/5%/10%/bounded canaries, cumulative safety budgets, live drift/reward guardrails, mandatory automatic rollback, and global kill-switch coverage.
- Stage-6 contextual safe policy learning with a stable feature schema, independent holdout doubly robust evaluation, HMAC-signed shadow-only manifests, and anytime-valid post-cutoff confidence gates.
- Stage-5 opt-in safe retrieval learning with low-risk bounded exploration, propensity logging, delayed verified outcomes, IPS/SNIPS OPE, and conservative promotion gates.
- Stage-4 statistical evaluation with paired bootstrap confidence intervals, held-out cost-sensitive calibration, and safety-bounded advisory retrieval policies.
- Stage-3 causal retrieval evaluation with algorithm-level ablations and deterministic retrieval/random/oracle seed interventions.
- Stage-2 retrieval evaluation with provider ablations, per-case multi-repo isolation, and explored-vs-utilized trajectory metrics.
- Agent Retrieval Bench-aligned file-level benchmark protocol with frozen snapshot validation, selective no-gold/wrong-repository controls, and per-task-type metrics.
- Typed public `WorkflowClient` / `TaskRequest` / `WorkflowResult` library API over the existing control-plane engine.
- Immutable run provenance with reproducibility keys, provider versions, workspace/index/config identity, and optional external artifact references.
- Explicit provider execution semantics and an opt-in deterministic retrieval cache.
- Async retriever adapters and a native async command-provider runner.
- Security policy, contribution guide, reproducibility guide, and audit compliance matrix.

### Fixed

- Production WAL mirroring now rejects SQLite runtimes affected by the 2026 WAL-reset corruption bug; doctor reports the runtime safety state when the production mirror is enabled.
- Synchronous command-provider stdout handles are explicitly closed after bounded reader shutdown.

## 2.3.0 - 2026-09-10

### Added

- Multi-platform Python 3.10-3.14 CI, focused Ruff/mypy gates, wheel/pipx/uv smoke installation, and measured benchmark regression checks.
- Single-source package versioning and modern PEP 639 project metadata.
- Trusted tag-release pipeline with PyPI OIDC publishing, native portable binaries, SHA-256 checksums, artifact attestations, GHCR provenance/SBOM, and distribution templates for WinGet, Homebrew, and Conda.

### Security

- GitHub Actions are pinned to immutable commit SHAs and release publishing uses least-privilege job permissions.
