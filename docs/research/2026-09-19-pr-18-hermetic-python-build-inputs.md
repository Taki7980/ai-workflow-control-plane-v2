# PR-18 — Hermetic Python Build Inputs

Date: 2026-09-19

## Problem

The project already pinned several direct tools, but Python build and CI inputs were still resolved through multiple independent paths:

- package smoke used `pip install --upgrade build pipx uv`;
- PyPI release used `pip install --upgrade build`;
- quality installed development extras independently;
- Code Review Graph and PyInstaller were installed independently;
- security tooling lived in a second requirements file;
- CI selected moving Python minor lines such as `3.14` rather than exact patch releases;
- the exact build toolchain identity was not emitted as durable release metadata.

That allowed the same source commit to be tested or released with different transitive tool versions as package indexes changed.

## Research and standards basis

### uv project locking and synchronization

https://docs.astral.sh/uv/concepts/projects/sync/

uv maintains a cross-platform lockfile containing exact resolutions. `uv lock --check` / `uv sync --locked` fail when the project metadata and lock no longer agree rather than silently refreshing the lock. Project synchronization is exact by default.

PR-18 uses the committed `uv.lock` as the Python tool resolution authority.

### uv on GitHub Actions

https://docs.astral.sh/uv/guides/integration/github/

Astral recommends the `astral-sh/setup-uv` action and supports pinning an exact uv release. PR-18 pins both:

- setup-uv action commit: `c771a70e6277c0a99b617c7a806ffedaca235ff9`
- uv: `0.12.14`

### PyPA pyproject build-system metadata

https://packaging.python.org/en/latest/specifications/pyproject-toml/

The `[build-system]` table defines the build backend and requirements needed to execute it. PR-18 replaces the open-ended backend requirement with an exact reviewed backend version.

### PyPA build isolation

https://build.pypa.io/en/latest/how-to/basic-usage.html

https://build.pypa.io/en/latest/reference/cli.html

`python -m build` normally creates a fresh isolated environment and installs declared build requirements there. `--no-isolation` instead uses the caller-provided environment and requires the caller to install the build dependencies.

PR-18 intentionally uses `--no-isolation` only after an exact `uv sync --locked` of the build group. This avoids creating a second independently resolved build environment.

### pip repeatable installs

https://pip.pypa.io/en/latest/topics/repeatable-installs/

Repeatable installations require controlled versions and artifact integrity. The committed uv lock records registry artifact SHA-256 hashes for the resolved Python tool graph.

### SLSA provenance

https://slsa.dev/spec/v1.2/provenance

https://slsa.dev/spec/v1.2/build-track-basics

SLSA provenance describes where, when, and how software artifacts were produced. PR-18 supplements existing GitHub attestations with an explicit Python toolchain record containing source revision, interpreter, resolver, selected direct tools, platform identity, and hashes of the declarative and resolved Python inputs.

## Design

### One reviewed Python resolution

`pyproject.toml` defines exact direct tool requirements using dependency groups:

- `build`
- `dev`
- `security`
- `crg`
- `portable`
- `package-smoke`

`uv.lock` records the cross-platform transitive resolution and artifact hashes.

The former duplicate `security/requirements.txt` is removed.

### Exact build backend

```toml
[build-system]
requires = ["setuptools==84.0.0"]
build-backend = "setuptools.build_meta"
```

Build jobs first sync the locked build group and then run:

```bash
uv run --locked --no-sync python -m build --no-isolation
```

This makes the pre-synchronized lock the source of the backend environment rather than allowing the build frontend to resolve a second environment.

### Exact interpreter patches in CI

Compatibility jobs retain the supported Python lines while pinning the patch releases used by this verification cycle:

- Python 3.11.16
- Python 3.12.14
- Python 3.13.15
- Python 3.14.7

Build/release tooling uses Python 3.14.7.

### Locked CI toolchains

CI uses the immutable setup-uv action commit and uv 0.12.14.

Examples:

```bash
uv lock --check
uv sync --locked --only-group dev
uv sync --locked --only-group build
uv sync --locked --only-group portable
uv run --locked --no-sync ...
```

No CI or release path performs `pip install --upgrade build`.

### Toolchain identity

`scripts/record_python_toolchain.py` records:

- source repository / commit / ref;
- Python implementation, exact version, cache tag;
- operating system and architecture;
- exact uv version;
- SHA-256 of `pyproject.toml`;
- SHA-256 of `uv.lock`;
- exact selected installed tool versions.

Python distributions publish and attest `python-build-toolchain.json`.
Portable binaries publish and attest a matching per-binary `.toolchain.json`.

This is supplemental metadata. Existing GitHub artifact attestations remain the hosted-build provenance boundary.

### CODEOWNERS

The lock and toolchain recorder are release authority and are protected alongside `pyproject.toml` and workflows:

- `/uv.lock`
- `/scripts/record_python_toolchain.py`

## Update protocol

Dependency/tool upgrades are deliberate source changes:

1. update exact direct requirements in `pyproject.toml`;
2. run the reviewed uv version to update `uv.lock`;
3. inspect both changes;
4. run `uv lock --check`;
5. run the normal security/test/release-contract gates.

CI must never repair a stale lock.

## Acceptance invariants

PR-18 adds repository tests requiring:

1. exact direct Python tool pins;
2. a universal committed lock;
3. SHA-256 hashes on registry artifacts in the lock;
4. immutable setup-uv action pin;
5. exact uv version;
6. locked sync in CI/release;
7. stale-lock checks before package/release work;
8. no mutable `pip install --upgrade build`;
9. no independent pip installs of CRG or PyInstaller;
10. exact CI Python patch versions;
11. locked build backend before `--no-isolation`;
12. toolchain identity containing project/lock hashes;
13. CODEOWNERS protection for lock/provenance inputs;
14. no one-time lock-generator workflow in the final repository.

## Scope boundary

PR-18 is limited to Python build/dev inputs.

It does not claim hermeticity for:

- Docker base image identity;
- Debian package indexes or apt package versions;
- container OS packages;
- BuildKit frontend identity;
- complete offline wheel vendoring.

Those belong to PR-19, which is responsible for hermetic container inputs, exact materials, and container reproducibility/provenance.
