# PR-19 — Hermetic Container Build Inputs

Date: 2026-09-19

## Scope

PR-19 closes the container-specific reproducibility gap left intentionally open by PR-18.

PR-18 made Python build inputs reviewable and locked. The container path still had mutable external state:

- `# syntax=docker/dockerfile:1` followed the latest stable frontend;
- both stages used `python:3.12-slim`, a mutable tag;
- the builder downloaded uv through pip during the image build;
- runtime executed `apt-get update && apt-get upgrade -y`;
- `git` and `ripgrep` came from whatever Debian mirror state existed at build time;
- GitHub workflows used whatever Buildx/BuildKit happened to be installed on the runner.

## Research basis

### Docker digest pinning

https://docs.docker.com/build/building/best-practices/

Docker documents that image tags are mutable. Pinning a base image by digest guarantees that a build uses the reviewed image content until the source is deliberately updated.

The same guidance recommends automated dependency tooling such as Docker Scout or Dependabot so digest-pinned projects still receive visible update proposals.

### Dockerfile frontend identity

https://docs.docker.com/reference/dockerfile/

A `# syntax=docker/dockerfile:1` directive tracks the latest stable frontend. PR-19 pins both a concrete frontend tag and immutable digest.

### BuildKit reproducible timestamps

https://docs.docker.com/build/ci/github-actions/reproducible-builds/

https://docs.docker.com/build/cache/invalidation/

BuildKit supports `SOURCE_DATE_EPOCH` for reproducible image/index/config and file timestamps. GitHub Actions guidance explicitly recommends deriving it from the Git commit timestamp when provenance should track the source revision.

PR-19 derives the timestamp from the checked-out commit and passes it to every CI/security/release container build.

BuildKit's reproducibility documentation distinguishes image/config/history timestamps from timestamps stored inside filesystem layers. The image/docker exporters therefore also use `rewrite-timestamp=true`; without that exporter option two no-cache builds can retain execution-time file metadata even when `SOURCE_DATE_EPOCH` is set.

### BuildKit SLSA provenance

https://docs.docker.com/build/metadata/attestations/slsa-provenance/

BuildKit supports SLSA provenance v1 and max mode. Max mode records detailed build parameters and material information. PR-19 uses:

```
--provenance=mode=max,version=v1
```

No secret is passed as a build argument. The only explicit build argument is `SOURCE_DATE_EPOCH`.

### BuildKit SBOM

https://docs.docker.com/build/metadata/attestations/sbom/

BuildKit can attach SPDX SBOM data and expose it through `docker buildx imagetools inspect`. PR-19 exports the release SBOM and verifies the expected locked runtime package versions.

### Debian Snapshot

https://snapshot.debian.org/

https://manpages.debian.org/trixie/apt/sources.list.5.en.html

Debian Snapshot provides timestamp-addressed historical archive states that can be used as APT sources. APT supports disabling `Check-Valid-Until` for historical snapshots.

PR-19 freezes both normal Debian and Debian Security repositories at:

`20260919T000000Z`

The direct packages resolved from that snapshot are:

- `git=1:2.47.3-0+deb13u1`
- `ripgrep=14.1.1-1+b4`

Transitive APT dependencies are also resolved from the same frozen repository state.

### SLSA v1.2

https://slsa.dev/spec/v1.2/provenance
https://slsa.dev/spec/v1.2/build-track-basics

SLSA provenance distinguishes source/build definition from resolved build dependencies. PR-19 makes the key OCI materials immutable in source and validates the resulting BuildKit provenance at release time.

## Live input discovery

The immutable values used here were not guessed from documentation. A temporary GitHub Actions workflow resolved them from the actual registries and Debian snapshot on 2026-09-19, then was removed.

### Dockerfile frontend

`docker/dockerfile:1.27.0`

Index digest:

`sha256:bde3983e9c939224420ddaf6b784cc30e09b035a4dea01f581230c50809f372e`

### Python base

`python:3.12.14-slim-trixie`

Index digest:

`sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9`

Linux/amd64 manifest:

`sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b`

### uv bootstrap image

`ghcr.io/astral-sh/uv:0.12.14`

Index digest:

`sha256:1946145b8706ad9e5c0e79a513f9e324b58d5e38126bb2c8b7dbfca61febeb45`

Linux/amd64 manifest:

`sha256:503548e4f528126e55a4834114fea2ea80ccd8c113147b9121b8766ace6394a6`

### Buildx / BuildKit

Buildx: `v0.37.0`

setup-buildx action commit:

`37fe631027851001ddb9b187196cc803df7f5f0e`

BuildKit: `moby/buildkit:v0.33.0`

Index digest:

`sha256:6c2fa84a6b61ccd72899dde4239f8d5717f05f9a8ca6f3cad185fb1a95a94de3`

## Design

### Immutable OCI materials

Every external `FROM` and the Dockerfile frontend use `tag@sha256:digest`. The human-readable tag documents intent while the digest supplies identity.

### uv without an ad-hoc network bootstrap

The old builder executed:

```
pip install uv==0.12.14
```

The version was fixed, but the artifact was still downloaded during the build outside the committed Python lock.

PR-19 instead copies the uv executable from the digest-pinned official uv OCI image.

### Frozen APT archive

Runtime replaces the normal Debian sources with the reviewed snapshot files in `packaging/container/debian.sources`.

There is no blanket `apt-get upgrade`.

Direct runtime packages are exact-version inputs in `packaging/container/runtime-packages.txt`.

### Pinned builder

Tests, Security, and Release all configure the same:

- setup-buildx action commit;
- Buildx v0.37.0;
- BuildKit v0.33.0 immutable image digest.

This removes the GitHub runner's preinstalled builder version from the effective build definition.

### Reproducibility gate

CI performs two independent no-cache Linux/amd64 builds with the same source commit timestamp and compares their image IDs.

This catches hidden time-based or mutable-input drift in the normal image build.

### Release provenance and SBOM

Release uses SLSA v1 max-mode provenance and an SPDX SBOM.

After pushing, the workflow exports both attached records with `imagetools inspect` and verifies:

- the pinned Python base material is present in provenance;
- the pinned uv image material is present in provenance;
- `git` appears in the SBOM at its locked Debian version;
- `ripgrep` appears in the SBOM at its locked Debian version.

Inspectable copies are attached to the draft GitHub Release and receive GitHub artifact attestations in addition to the OCI-attached BuildKit attestations.

## Update policy

Immutable inputs deliberately do not update themselves.

A container refresh should:

1. review a proposed Docker base digest update;
2. resolve and record the new Python/uv/frontend/BuildKit digest where applicable;
3. choose a new Debian snapshot timestamp;
4. resolve explicit runtime package versions against that snapshot;
5. update `packaging/container/inputs.json` and related source files together;
6. run the two-build reproducibility gate;
7. run container vulnerability scanning;
8. merge only after normal Tests, Security, and CodeQL gates are green.

Dependabot is enabled for Docker inputs so base-image changes become reviewable PRs rather than silent tag movement.

## What PR-19 does not claim

This is a controlled, reproducible networked build, not a fully offline build.

The build still fetches immutable OCI objects and a timestamp-addressed Debian archive over the network. Availability of those services is therefore required unless artifacts are mirrored internally.

The reproducibility gate establishes identical image identity for the same source, platform, pinned builder and locked external inputs in CI. It does not claim bit-for-bit equivalence across unrelated CPU architectures or different platform targets.

That stronger offline/mirrored supply-chain model is not necessary for the current control-plane threat model and would add significant operational complexity without proportional value.
