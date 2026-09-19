# Distribution and release

AI Workflow keeps its Python core dependency-free while offering isolated and portable installation paths.

Python-based installations require **Python 3.11+**. Python 3.12+ is the recommended deployment baseline.

## Publication status and source of truth

Package-manager templates and release automation in this repository are not proof that a package has been published to PyPI, Homebrew, WinGet, Conda, GHCR, or GitHub Releases. Verify the target registry/release before using a published-package command.

The package version has one source of truth: `ai_workflow._version.__version__`. Tagged releases must use the matching `vX.Y.Z` tag.

## Released Python CLI lifecycle

Once `ai-workflow-control-plane` is published, **uv is the preferred isolated CLI path**:

```bash
uv tool install ai-workflow-control-plane
ai-workflow --version
ai-workflow setup
ai-workflow doctor --strict

uv tool upgrade ai-workflow-control-plane
uv tool uninstall ai-workflow-control-plane
```

pipx remains first-class for Python users:

```bash
pipx install ai-workflow-control-plane
ai-workflow --version

pipx upgrade ai-workflow-control-plane
pipx uninstall ai-workflow-control-plane
```

Until a package release is actually available, install the current Git source instead:

```bash
uv tool install git+https://github.com/Taki7980/ai-workflow-control-plane-v2.git
# or
pipx install git+https://github.com/Taki7980/ai-workflow-control-plane-v2.git
```

For contributor development, use the committed universal lock with the same uv version as CI:

```bash
uv sync --locked
uv lock --check
uv run --locked --no-sync python -m unittest discover -s tests -v
```

Normal development and CI must not perform opportunistic dependency upgrades. Changes to Python build/development tooling are reviewed as paired changes to `pyproject.toml` and `uv.lock`.

## Portable binary / bootstrap lifecycle

The bootstrap installers are convenience wrappers around immutable GitHub Release binaries. They verify `SHA256SUMS` before installation.

With no explicit version, the installers resolve the **latest stable** GitHub Release. Pinning remains available for reproducibility:

```bash
./install.sh
AI_WORKFLOW_VERSION=2.4.0 ./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
.\install.ps1 -Version 2.4.0
```

Re-run the installer to upgrade or replace the portable executable. To uninstall a default Unix installation:

```bash
rm -f "$HOME/.local/bin/ai-workflow"
```

For Windows, remove `%LOCALAPPDATA%\Programs\AIWorkflow\ai-workflow.exe` and remove that install directory from the user `PATH` if it is no longer used.

Each successful bootstrap install prints the resolved version, confirms `SHA-256 verified`, and prints an optional provenance command:

```bash
gh attestation verify /path/to/ai-workflow \
  --repo Taki7980/ai-workflow-control-plane-v2
```

Checksums establish byte integrity relative to release metadata. GitHub artifact attestations establish build provenance; neither is a vulnerability scan.

## Docker / GHCR lifecycle

```bash
docker build -t ai-workflow:local .
docker run --rm -v "$PWD:/workspace" ai-workflow:local doctor --strict
```

Tagged releases are designed to publish `ghcr.io/taki7980/ai-workflow-control-plane-v2:vX.Y.Z` with SBOM/provenance metadata. Remove an unused local image with:

```bash
docker image rm ghcr.io/taki7980/ai-workflow-control-plane-v2:vX.Y.Z
```

## Release contract

A `vX.Y.Z` tag must match `ai_workflow._version.__version__`. Before release work starts, the workflow verifies that the committed `uv.lock` still matches `pyproject.toml`. Python wheel/sdist builds and PyInstaller builds use the exact locked toolchain rather than independently resolving build tools at release time. Each release records a machine-readable toolchain manifest containing the Python version, uv version, selected build-tool versions, source SHA, platform identity, and SHA-256 digests of `pyproject.toml` and `uv.lock`.

The tag workflow creates a draft release, builds wheel/sdist, builds PyInstaller 6.22.3 executables natively on Linux x86_64, Windows x86_64, macOS arm64 and macOS x86_64, publishes a GHCR container, generates `SHA256SUMS`, renders package-manager manifests from those exact checksums, attests artifacts and toolchain manifests, and publishes the draft only after required build jobs succeed.

A post-publication verification job then downloads the public release, verifies every checksum-listed artifact, verifies GitHub attestations for Python distributions, portable binaries, checksums and rendered manifests, verifies the OCI image attestation, and performs a pinned bootstrap-install smoke.

PyInstaller builds are native because PyInstaller is not a cross-compiler.

## PyPI Trusted Publishing activation

The release workflow intentionally contains no PyPI password or API token. Before the first real release, configure the PyPI project (or a pending trusted publisher) for this GitHub repository, workflow file `.github/workflows/release.yml`, and environment `pypi`. The publish job requests `id-token: write` only at job scope.

## Package-manager submission inputs

The renderer emits deterministic submission inputs from the same release checksums:

- WinGet version, installer and default-locale manifests using schema 1.12.0;
- a Homebrew formula using exact Linux/macOS binary SHA-256 values;
- a Conda recipe using the exact sdist SHA-256 and Python 3.11+.

These are **submission inputs**, not evidence that the package has been accepted into Homebrew, WinGet or Conda.

## CI installation contract

Every pull request exercises wheel, pipx, `uv tool`, native portable binaries on Linux/Windows/macOS, Docker, and checksum-verifying Unix/Windows bootstrap installers. Bootstrap smoke uses deterministic localhost fixtures and does not depend on a live release.

## Rerun and failure behavior

A failed release remains a draft. Existing draft releases are reused on rerun, assets are uploaded with `--clobber`, checksums are regenerated from release payloads, and the draft is made public only by the final successful build job. The downstream verification job does not mutate the release.
