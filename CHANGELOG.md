# Changelog

All notable repository changes are summarized here. The project follows semantic versioning for package releases.

## Unreleased

### Added

- Agent Retrieval Bench-aligned file-level benchmark protocol with frozen snapshot validation, selective no-gold/wrong-repository controls, and per-task-type metrics.
- Typed public `WorkflowClient` / `TaskRequest` / `WorkflowResult` library API over the existing control-plane engine.
- Immutable run provenance with reproducibility keys, provider versions, workspace/index/config identity, and optional external artifact references.
- Explicit provider execution semantics and an opt-in deterministic retrieval cache.
- Async retriever adapters and a native async command-provider runner.
- Security policy, contribution guide, reproducibility guide, and audit compliance matrix.

### Fixed

- Synchronous command-provider stdout handles are explicitly closed after bounded reader shutdown.

## 2.3.0 - 2026-09-10

### Added

- Multi-platform Python 3.10-3.14 CI, focused Ruff/mypy gates, wheel/pipx/uv smoke installation, and measured benchmark regression checks.
- Single-source package versioning and modern PEP 639 project metadata.
- Trusted tag-release pipeline with PyPI OIDC publishing, native portable binaries, SHA-256 checksums, artifact attestations, GHCR provenance/SBOM, and distribution templates for WinGet, Homebrew, and Conda.

### Security

- GitHub Actions are pinned to immutable commit SHAs and release publishing uses least-privilege job permissions.
