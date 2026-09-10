# Packaging, Release, and Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the audit's packaging, CI quality, release supply-chain, and distribution recommendations while keeping the runtime dependency-free.

**Architecture:** Make PyPI the canonical package source, derive all version surfaces from one module, separate CI quality/compatibility/package/benchmark jobs, and build native release artifacts on their target OS. Distribution manifests are rendered from the release version plus verified SHA256SUMS so no placeholder checksum can ship as a real manifest.

**Tech Stack:** Python 3.10+, setuptools>=77, build, ruff, mypy, PyInstaller, GitHub Actions/OIDC, Docker/OCI, pipx, uv, WinGet YAML, Homebrew Ruby formula, Conda recipe.

**Spec:** Technical Audit and Improvement Plan for `ai-workflow-control-plane-v2`.

## Global Constraints

- Zero mandatory runtime dependencies.
- PyPI is canonical for ordinary Python installation.
- GitHub Actions use immutable full commit SHA pins and least-privilege permissions.
- PyPI publication uses Trusted Publishing/OIDC rather than stored API tokens.
- Build once, verify, then publish the exact verified artifacts.
- Native binaries are built on their target OS and verified before release.
- Release binaries and bootstrap installers are SHA-256 verified.
- Docker runs as non-root and contains Git plus ripgrep.
- Keep `ai-workflow-setup` compatibility but document `ai-workflow setup` as normal first-run flow.

---

### Task 1: Single-source package identity and modern metadata
- [ ] Write failing metadata/version tests.
- [ ] Verify RED.
- [ ] Add `_version.py`, dynamic setuptools version, PEP 639 license fields, project URLs and `dev` extra containing build/ruff/mypy.
- [ ] Add `ai-workflow --version` through a lightweight entrypoint.
- [ ] Verify package metadata from a built wheel.

### Task 2: CI quality and package jobs
- [ ] Add pinned checkout/setup-python actions and explicit read-only default permissions.
- [ ] Keep Linux Python 3.10-3.14 and Windows coverage; add macOS.
- [ ] Add focused Ruff, mypy/check-untyped-defs, compile, build, clean-wheel, pipx and uv smoke jobs.
- [ ] Keep benchmark regression as a separately auditable gate.

### Task 3: Release workflow and provenance
- [ ] Build sdist/wheel once and verify them before publishing.
- [ ] Publish with PyPI Trusted Publishing (`id-token: write`) in the publication job only.
- [ ] Build PyInstaller binaries natively for Linux/macOS/Windows supported runner architectures.
- [ ] Smoke-test every binary and generate SHA256SUMS.
- [ ] Produce GitHub build provenance attestations and an SBOM/attestation where supported.
- [ ] Upload verified artifacts to a GitHub release without third-party unpinned release actions.

### Task 4: Docker/OCI distribution
- [ ] Add multi-stage Dockerfile and `.dockerignore`.
- [ ] Install Git and ripgrep in runtime image.
- [ ] Create a non-root user and expose `ai-workflow` as the entrypoint.
- [ ] Add build and mounted-repository smoke tests.

### Task 5: Bootstrap installers and package-manager channels
- [ ] Add POSIX and PowerShell installers requiring or resolving an explicit release version and validating SHA-256 before execution/install.
- [ ] Add a manifest renderer driven by release version and `SHA256SUMS`.
- [ ] Render WinGet, Homebrew, and Conda distribution templates with no fake checksum values.
- [ ] Document submission/tap/channel lifecycle separately from local manifest generation.

### Task 6: Contributor/security/release documentation
- [ ] Add `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and `docs/distribution.md`.
- [ ] Update README installation/version language to match the canonical package identity.
- [ ] Add smoke tests for wheel, pipx/uv, binary and Docker installation paths.
- [ ] Run the complete CI/release dry-run surface before opening the PR.
