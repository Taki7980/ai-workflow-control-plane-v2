# PR-34 — Supply-chain and release reproducibility

Date: 2026-09-28

## Scope

PR-34 hardens the release path without adding a generic supply-chain platform.
The project already had SHA-pinned GitHub Actions, locked Python tooling,
checksum-verified bootstrap installers, container reproducibility checks,
container provenance/SBOM export, GitHub artifact attestations, PyPI Trusted
Publishing, and a protected-release authorization gate.

The remaining high-value gaps were:

1. Python wheel/sdist reproducibility was assumed from pinned inputs but not
   measured.
2. The PyPI OIDC job also performed the build, giving the publishing trust
   boundary more code and tooling than necessary.
3. Pinned GitHub Actions had no Dependabot version-update configuration.
4. There was no repository-wide regression test requiring external actions to
   stay pinned to immutable full commit SHAs.

## Research refreshed 2026-09-28

### GitHub Actions secure use

GitHub's secure-use guidance states that pinning an action to a full-length
commit SHA is the immutable-reference option for actions. PR-34 keeps that
policy and adds a test that rejects mutable external action references.

https://docs.github.com/en/actions/reference/security/secure-use

GitHub also documents Dependabot support for GitHub Actions, including actions
already pinned by commit SHA.

https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/auto-update-actions

### PyPI Trusted Publishing and attestations

PyPI's Trusted Publisher security guidance recommends separating build from
publish so the publishing job contains only retrieval of prebuilt distributions
and the publish action. This minimizes the code that can access the PyPI OIDC
identity.

https://docs.pypi.org/trusted-publishers/security-model/

The official PyPA publishing action generates PEP 740-compatible PyPI
attestations by default. Those attestations prove publisher identity and file
integrity, not package trustworthiness.

https://docs.pypi.org/attestations/producing-attestations/
https://docs.pypi.org/attestations/security-model/

### GitHub artifact attestations

GitHub artifact attestations bind artifacts to repository/workflow/source
identity and can be verified by consumers. GitHub explicitly warns that
attestations establish provenance and integrity, not that an artifact is safe.

https://docs.github.com/en/actions/concepts/security/artifact-attestations
https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations

### Reproducible builds

The Reproducible Builds project defines `SOURCE_DATE_EPOCH` as a standard
mechanism for replacing build-time timestamps with a stable source-derived
timestamp where supported.

https://reproducible-builds.org/docs/source-date-epoch/

PR-34 does not infer reproducibility from `SOURCE_DATE_EPOCH`. It builds the
Python distributions twice from two clean `git archive HEAD` source trees and
compares the release artifacts byte-for-byte.

The first CI run provided useful counter-evidence: the wheel was already
byte-identical, but Setuptools produced different raw `.tar.gz` sdists from the
two clean source trees even with the same `SOURCE_DATE_EPOCH`. This is
consistent with the long-standing Setuptools sdist timestamp/gzip-header issue.

https://github.com/pypa/setuptools/issues/2133

The Python packaging specification requires modern POSIX.1-2001 pax tar for
sdists and defines the safe archive feature boundary.

https://packaging.python.org/en/latest/specifications/source-distribution-format/

Rather than adding another third-party build backend/wrapper, PR-34 therefore
normalizes each project-built sdist with Python's standard library before the
comparison and before publication. The normalizer fixes gzip/tar timestamps,
uid/gid/user/group fields, member order and portable file modes while preserving
file bytes, enforcing one filename-matching top-level directory, requiring
`pyproject.toml` and `PKG-INFO`, and rejecting unsafe paths, links and device
members.

### SLSA

SLSA v1.2 treats provenance as evidence describing how an artifact was
produced, with stronger levels adding authenticity/isolation properties.
Reproducibility is useful independent evidence but is not treated as a
substitute for provenance or build isolation.

https://slsa.dev/spec/v1.2/provenance

## Design

### Python distribution reproducibility gate

Both CI package smoke and the release build:

1. derive `SOURCE_DATE_EPOCH` from the exact Git commit timestamp;
2. create two independent clean source trees with `git archive HEAD`;
3. build wheel + sdist in each tree using the same locked build toolchain;
4. normalize each raw sdist into deterministic, spec-compatible pax/gzip
   metadata using the same source timestamp;
5. compare artifact filenames, sizes, and SHA-256 digests;
6. fail if either artifact is absent or any bytes differ.

Release builds emit:

`release-metadata/python-reproducibility.json`

The report records the source timestamp and exact artifact digests. The first
verified candidate—including its normalized sdist—becomes the release artifact;
a third unverified rebuild is not performed.

### PyPI trust-boundary split

The release workflow now separates:

- `build-python-distributions`: checkout, locked toolchain, double build,
  smoke test, GitHub attestation, draft-release upload.
- `publish-pypi`: the `pypi` environment and OIDC identity. It only downloads
  wheel/sdist assets from the draft release, verifies their GitHub attestations
  against the exact source SHA/ref/release workflow, and invokes the official
  PyPA publishing action.

The publish job does not checkout source, install Python/uv, run build tools, or
create attestations.

### Action pin maintenance

All external workflow actions are required by tests to use full 40-character
commit SHAs. Dependabot is configured for the `github-actions` ecosystem so
updates to pinned actions are surfaced as reviewable PRs.

## Explicit non-goals

- No claim that PyInstaller portable binaries are reproducible. They remain
  platform-built, smoke-tested, toolchain-recorded, checksummed, and attested.
- No second Python SBOM generator is introduced. The runtime Python package has
  no declared dependencies, while the container release already exports and
  verifies SPDX SBOM and SLSA provenance. Adding another scanner would expand
  the trusted toolchain without a demonstrated threat-model benefit.
- No claim that GitHub/PyPI attestations prove code safety or correctness.
- Repository files cannot enforce organization/repository UI policies such as
  tag protection or the GitHub setting that requires SHA-pinned actions; the
  release authorization and static tests provide repository-level evidence,
  while the UI policy remains operator-controlled.

## Acceptance criteria

- Python wheel and sdist are independently rebuilt and byte-identical in CI.
- Release uses the exact reproducibility-verified artifacts.
- Machine-readable reproducibility evidence is attested and attached.
- PyPI publishing job contains no build toolchain or source checkout.
- PyPI job verifies GitHub attestations before publishing.
- Every external GitHub Action reference is a full commit SHA.
- Dependabot tracks GitHub Actions updates.
- Existing container reproducibility/provenance/SBOM gates remain unchanged.
- Full CI/security/CodeQL/package/container/binary matrix passes before merge.
- PR remains unmerged until explicitly merged by the user.
