# Installation and Distribution Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI Workflow's existing release system genuinely installable, lifecycle-safe, and verifiable across Python-tool, portable-binary, container, and package-manager paths.

**Architecture:** Keep the zero-runtime-dependency Python core and the existing tag-driven release workflow. Tighten the supported Python floor, make bootstrap installers resolve release version from one source of truth, extend CI to exercise every user-facing installation class, verify release provenance after publication, and add deterministic tests/docs for package-manager manifests and upgrade/uninstall workflows.

**Tech Stack:** Python 3.11+, setuptools/PEP 621, GitHub Actions, PyPI Trusted Publishing, pipx, uv, PyInstaller, Docker/GHCR, GitHub artifact attestations, Homebrew formula templates, WinGet 1.12 manifests, Conda recipe templates.

**Spec:** PR-05 / I-017–I-021 from the AI Workflow v2 hardening tracker, grounded in the 2026-09-15 repository deep-research report and current 2026 Python/PyPI/GitHub/pipx/uv/PyInstaller/WinGet documentation.

## Global Constraints

- Preserve the dependency-free runtime core.
- Preserve `ai-workflow setup` as the canonical post-install entry point.
- Do not create or publish a real release/tag from this PR.
- Preserve PyPI Trusted Publishing; do not add PyPI API tokens.
- Preserve SHA-pinned GitHub Actions.
- Preserve native PyInstaller builds per target OS; PyInstaller is not a cross-compiler.
- Keep Homebrew/WinGet/Conda files as generated submission inputs; do not claim registry acceptance.
- Do not add Kubernetes/Helm/cloud-marketplace work in PR-05.
- TDD: new behavior must have a failing regression/contract test before implementation.
- Do not merge PR-05 automatically.

---

### Task 1: Raise the supported Python floor — I-017

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/tests.yml`
- Modify: `packaging/conda/meta.yaml.in`
- Modify: `README.md`
- Modify: `docs/distribution.md`
- Test: `tests/test_distribution_contracts.py`

**Interfaces:**
- Package metadata declares `requires-python = ">=3.11"`.
- Mypy target becomes Python 3.11.
- Required CI compatibility matrix is Linux 3.11–3.14 plus Windows/macOS 3.14.
- Conda host/run requirements are `python >=3.11`.

- [ ] Add contract tests that fail while `pyproject.toml` and Conda still allow 3.10 and while required CI still includes 3.10.
- [ ] Change `requires-python` and mypy target to 3.11.
- [ ] Remove Python 3.10 from required compatibility CI.
- [ ] Update Conda template to 3.11+.
- [ ] Update user docs to 3.11+ and recommend 3.12+ for deployment.
- [ ] Run focused distribution tests.

### Task 2: Single-source bootstrap installer versioning — I-018

**Files:**
- Modify: `install.sh`
- Modify: `install.ps1`
- Test: `tests/test_distribution_contracts.py`

**Interfaces:**
- Shell explicit pin: `AI_WORKFLOW_VERSION=2.4.0 ./install.sh`.
- PowerShell explicit pin: `./install.ps1 -Version 2.4.0`.
- With no explicit version, both installers resolve the latest stable GitHub Release at runtime.
- Resolved tag must match `v<PEP440-ish release version>`; reject malformed/prerelease-looking tags for the default stable path.
- Both installers continue SHA-256 verification before install.
- Successful install output includes resolved version, checksum verification, and an optional `gh attestation verify` command for the downloaded artifact.

- [ ] Add tests proving neither installer contains a hard-coded package version default.
- [ ] Add tests proving explicit pinning remains supported.
- [ ] Add tests proving output contains checksum and provenance-verification guidance.
- [ ] Implement latest-release resolution without requiring jq or Python on the target machine.
- [ ] Preserve unsupported-platform and checksum-failure behavior.
- [ ] Run focused tests.

### Task 3: Complete installation smoke coverage — I-019

**Files:**
- Modify: `.github/workflows/tests.yml`
- Create: `scripts/smoke_bootstrap_install.py`
- Test: `tests/test_distribution_contracts.py`

**Interfaces:**
- Existing wheel, pipx, and uv smoke remain.
- Native portable executable smoke runs on Linux, Windows, and macOS.
- Docker image smoke runs `ai-workflow --version`.
- Bootstrap installer smoke uses a local deterministic fake release payload/checksum and never depends on a real GitHub Release.

- [ ] Add tests for the deterministic bootstrap-smoke fixture/helper.
- [ ] Add a portable-binary smoke matrix using the current pinned PyInstaller release.
- [ ] Update PyInstaller pin to the current tested stable release (6.22.3 at implementation time).
- [ ] Add Docker build/run smoke on Ubuntu.
- [ ] Add Linux bootstrap installer smoke against a local HTTP fixture.
- [ ] Add Windows PowerShell bootstrap installer smoke against a local HTTP fixture or equivalent deterministic local source supported by the installer.
- [ ] Ensure no release smoke requires live PyPI/GitHub publication.
- [ ] Run the full installation-smoke jobs.

### Task 4: Verify release artifacts after publication — I-020

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `tests/test_source_release_governance.py`
- Test: `tests/test_distribution_contracts.py`

**Interfaces:**
- Add `verify-release` after `finalize-release`.
- Download the now-public release assets.
- Verify `SHA256SUMS` against every checksum-listed asset.
- Verify GitHub artifact attestations for Python distributions, portable binaries, checksum file, and rendered package-manager manifests.
- Verify the pushed OCI image attestation by immutable release tag.
- Smoke the published portable binary via the bootstrap installer pinned to `GITHUB_REF_NAME`.

- [ ] Add workflow contract tests that fail until verification is downstream of finalization.
- [ ] Add contract tests requiring checksum verification and `gh attestation verify`.
- [ ] Implement the post-publication verification job with least required permissions.
- [ ] Keep publication draft until existing required build jobs succeed.
- [ ] Do not claim artifact attestation proves vulnerability-freedom; document it as provenance/integrity evidence.
- [ ] Run release-governance tests.

### Task 5: Package-manager contracts and lifecycle docs — I-021

**Files:**
- Modify: `scripts/render_distribution_manifests.py`
- Modify: `docs/distribution.md`
- Modify: `README.md`
- Test: `tests/test_distribution_contracts.py`

**Interfaces:**
- Deterministic renderer accepts release `SHA256SUMS` and emits:
  - WinGet version/installer/default-locale manifests at schema 1.12.0.
  - Homebrew formula referencing exact versioned release assets and SHA-256.
  - Conda recipe referencing exact sdist and Python >=3.11.
- Docs make `uv tool install ai-workflow-control-plane` the primary released-package path, with pipx first-class.
- Docs include upgrade/uninstall commands for uv, pipx, bootstrap/portable binary and container paths.
- Docs distinguish “template generated” from “published in Homebrew/WinGet/Conda”.

- [ ] Add fixture-based renderer tests with deterministic fake SHA-256 values.
- [ ] Assert every expected output contains no unresolved `@PLACEHOLDER@`.
- [ ] Assert rendered WinGet manifests use schema 1.12.0 and the exact Windows SHA-256.
- [ ] Assert Homebrew uses the exact macOS/Linux artifact hashes.
- [ ] Assert Conda uses the exact sdist hash and Python >=3.11.
- [ ] Document install → verify → upgrade → uninstall for uv and pipx.
- [ ] Document bootstrap installer pinning/latest behavior and manual portable-binary removal.
- [ ] Document that Homebrew/WinGet/Conda templates are submission inputs, not proof of registry publication.
- [ ] Run all distribution contract tests.

### Final verification

- [ ] Run all unit tests on Linux Python 3.11–3.14.
- [ ] Run Windows/macOS compatibility.
- [ ] Run wheel, pipx, uv, portable-binary, Docker, and bootstrap smoke jobs.
- [ ] Run benchmark regression and real CRG contract.
- [ ] Run Python security, secret scan, and container scan.
- [ ] Review the diff for PR-06+ scope creep.
- [ ] Open PR-05 ready for review and leave it unmerged.
