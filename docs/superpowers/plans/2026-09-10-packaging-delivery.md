# Packaging and Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PyPI/pipx/uv the canonical Python distribution path and add reproducible CI/package/binary/container release surfaces.

**Architecture:** Keep the wheel dependency-free, modernize PEP 639 metadata, split CI concerns, build/test wheel and sdist on clean environments, add OIDC Trusted Publishing release workflow, native PyInstaller binary jobs, checksums/attestations, and a minimal non-root Docker image.

**Tech Stack:** setuptools 77+, GitHub Actions, PyPA build/publish actions, PyInstaller, Docker.

**Spec:** Technical Audit and Improvement Plan — PR D.

## Global Constraints

- No long-lived PyPI token in repository configuration.
- Release publication only on version tags and GitHub environment protection.
- Native binaries built on their target OS; do not treat PyInstaller as a cross-compiler.
- Wheel install smoke test must execute `ai-workflow --help` and `doctor` from an isolated environment.

---

### Task 1: Package metadata and CLI version

**Files:** Modify `pyproject.toml`, `ai_workflow/__init__.py`, `ai_workflow/cli.py`; Test version command.

- [ ] Upgrade build-system floor to setuptools 77 and use SPDX `license = "MIT"` plus `license-files`.
- [ ] Add project URLs and `dev` optional dependencies for build/ruff/mypy.
- [ ] Add `ai-workflow --version` using package version metadata with source fallback.

### Task 2: CI quality/package/benchmark jobs

**Files:** Replace `.github/workflows/tests.yml`; add benchmark baseline checker and tests.

- [ ] Preserve Ubuntu 3.10–3.14 and Windows 3.14 unit tests; add macOS 3.14 smoke.
- [ ] Add quality job for compileall, ruff, and mypy with explicit configuration.
- [ ] Add package job building wheel/sdist then installing the wheel into a clean venv and running CLI smoke tests.
- [ ] Add benchmark regression thresholds against a checked-in baseline with tolerances, not metric-existence-only checks.

### Task 3: Trusted Publishing and release assets

**Files:** Create `.github/workflows/release.yml`, `packaging/entrypoint.py`, release helper scripts/docs.

- [ ] Build wheel/sdist once and publish through `pypa/gh-action-pypi-publish` with OIDC `id-token: write` on `v*` tags.
- [ ] Build PyInstaller binaries natively on Linux/macOS/Windows and smoke-test each artifact.
- [ ] Generate SHA256 checksums and GitHub artifact attestations where supported.

### Task 4: Docker and docs

**Files:** Create `Dockerfile`, `.dockerignore`, `docs/distribution.md`, `SECURITY.md`, `CONTRIBUTING.md`.

- [ ] Multi-stage-build the wheel and install into a slim runtime containing Git and ripgrep.
- [ ] Run as non-root UID 10001 with `/workspace` workdir.
- [ ] Document pipx, uv, wheel, binaries, Docker, provenance verification, optional external-provider limitations, and release process.
- [ ] Run full CI/package smoke.
