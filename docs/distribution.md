# Distribution and release

AI Workflow keeps its Python core dependency-free while offering isolated and portable installation paths.

## Preferred installation order

After a version is published, prefer `pipx install ai-workflow-control-plane` or `uv tool install ai-workflow-control-plane`. These install the CLI in an isolated environment. Portable GitHub release executables are the no-Python alternative. Docker is intended primarily for CI and reproducible automation where a repository is mounted at `/workspace`.

The repository also carries checksum-verifying bootstrap installers (`install.sh` and `install.ps1`) plus release-rendered WinGet, Homebrew and Conda manifest material. Package-manager community publication is a separate external submission step and is not claimed merely because templates exist in this repository.

## Release contract

A `vX.Y.Z` tag must match `ai_workflow._version.__version__`. The tag workflow creates a draft release, builds wheel/sdist, builds PyInstaller 6.22.2 executables natively on Linux x86_64, Windows x86_64, macOS arm64 and macOS x86_64, publishes a GHCR container, generates SHA256SUMS, renders package-manager manifests from those exact checksums, attests artifacts, and publishes the draft only after required jobs succeed.

PyInstaller builds are native because PyInstaller is not a cross-compiler. The container image deliberately includes Git and ripgrep because those are observable optional capabilities of the control plane, and it runs as an unprivileged user.

## PyPI Trusted Publishing activation

The release workflow intentionally contains no PyPI password or API token. Before the first real release, configure the PyPI project (or a pending trusted publisher) for this GitHub repository, workflow file `.github/workflows/release.yml`, and environment `pypi`. The publish job requests `id-token: write` only at job scope.

## Verifying artifacts

Every bootstrap installer verifies the selected executable against the release's `SHA256SUMS` before installation. GitHub artifact attestations provide a second provenance check. With GitHub CLI installed, a release artifact can be checked with `gh attestation verify <artifact> --repo Taki7980/ai-workflow-control-plane-v2`.

Checksums prove byte integrity relative to the release metadata; attestations bind build provenance to the repository/workflow identity. Use both for high-trust installation.

## Docker

Build locally with `docker build -t ai-workflow .`. Run against the current checkout with `docker run --rm -v "$PWD:/workspace" ai-workflow doctor --strict`. Tagged releases additionally publish `ghcr.io/taki7980/ai-workflow-control-plane-v2:vX.Y.Z`.

## Package-manager submissions

WinGet currently expects multi-file community manifests, so the renderer emits version, installer and default-locale manifests using schema 1.12.0. Homebrew and Conda outputs are also rendered from release checksums. These generated files are submission inputs; acceptance into third-party repositories remains governed by those projects' review processes.

## Rerun and failure behavior

A failed release remains a draft. Existing draft releases are reused on a rerun, assets are uploaded with `--clobber`, checksums are regenerated from release payloads, and the draft is made public only by the final successful job. This avoids advertising a partially built release as complete.
