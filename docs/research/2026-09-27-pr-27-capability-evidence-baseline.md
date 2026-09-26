# PR-27 — Capability evidence baseline

Date: 2026-09-27  
Baseline: `c5757873bdea2124e6c077fc2ce35a7e4396531c`

## Problem

AI Workflow already has extensive tests, security gates, research notes, benchmarks,
and release controls, but the evidence is distributed across Markdown, Python modules,
tests, benchmark fixtures, and GitHub Actions. The historical
`docs/audit-compliance.md` matrix is useful, but it is point-in-time documentation.
It cannot fail CI when a capability claim becomes disconnected from the code or tests
that support it.

That creates a documentation/evidence drift risk: a statement can remain in README or
research documentation after its implementation, verification, default status, or
limitations change.

## Research basis

Three current sources shape this PR.

1. **Agent Retrieval Bench (2026)** evaluates repository retrieval against frozen
   base-commit repositories, separates retrieval quality from downstream patch
   generation, and reports that no single retrieval family dominates all task types.
   This supports explicit evidence scope and prevents a retrieval benchmark from being
   presented as proof of downstream coding correctness.
   - https://arxiv.org/abs/2607.24882

2. **OpenSSF machine-readable signals guidance (2026)** argues for automated,
   machine-readable evidence while explicitly distinguishing transparency signals from
   assurance or guarantees. This is the core semantic rule of the new manifest.
   - https://openssf.org/blog/2026/05/29/aligning-on-machine-readable-signals-as-the-foundation-for-due-diligence/

3. **SLSA 1.2 provenance** defines provenance as verifiable information about where,
   when, and how an artifact was produced. The same design principle applies here:
   evidence identity should be explicit and machine-checkable, without claiming that
   provenance itself proves behavioral correctness.
   - https://slsa.dev/spec/v1.2/provenance

## Design

PR-27 adds `evidence/capabilities.json` as a repository-owned claim/evidence index.

Every capability records:

- a stable capability ID;
- the claim being made;
- scope;
- implementation status;
- evidence level;
- whether it is a production default;
- implementation paths;
- verification paths;
- benchmark evidence when applicable;
- research references;
- explicit limitations.

The schema deliberately distinguishes:

- `verified`: implementation behavior is covered by repository tests/CI;
- `measured`: repository benchmark evidence also exists;
- `experimental`: implemented research machinery that is not a production claim;
- `external`: repository work exists but assurance depends on external activation.

Experimental capabilities must not be production defaults.

## Validation contract

`scripts/check_capability_evidence.py` fails closed when:

- the schema or baseline identity is malformed;
- a capability/research ID is duplicated;
- an implementation/test/benchmark path is missing;
- a path escapes the repository;
- an implemented capability is labelled experimental evidence;
- an experimental/external capability is marked production-default;
- a measured claim has no benchmark evidence;
- a capability lacks test/CI verification;
- a research reference is unknown;
- limitations are omitted.

The quality workflow runs this validator on every push and pull request.

## Baseline result

The initial manifest maps 15 major capabilities. It intentionally classifies the
following as experimental rather than production-proven:

- benchmark corpus v2 as publication-scale evidence;
- adaptive retrieval learning;
- controlled policy deployment.

It also records limitations for implemented systems such as CRG retrieval, the provider
sandbox, replay verification, SQLite WAL mirroring, and release automation.

## CI-discovered baseline drift repair

The first exact-head security run exposed a pre-existing reproducibility drift on
`main`: Dependabot had updated only the Dockerfile while the reviewed container
input manifest, setup-uv workflow pins, and hermetic tests still described older
inputs.

The first repair synchronized those contracts to the then-current Dockerfile. The
next exact-head container scan correctly exposed a second problem: the pinned
`python:3.14.6-slim-trixie` base contained fixable HIGH-severity Debian
vulnerabilities, including OpenSSL and util-linux findings. The scan was not
suppressed and no CVE ignore was added.

PR-27 therefore upgrades the base to the current official Python 3.14.7 image and
records the immutable registry identities resolved from Docker Hub:

- Python ref: `python:3.14.7-slim-trixie`
- Python index digest: `sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d`
- Python linux/amd64 manifest: `sha256:7bf6c3111fe094f8ee1a1cbcdc63c4cfb345b0e3df42d5aa9a90b3b4b022ab6d`
- uv ref: `ghcr.io/astral-sh/uv:0.12.19`
- uv index digest: `sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424`
- uv linux/amd64 manifest: `sha256:d46db4c7b7f2e75ff80aeef95da4c2c6ff1ad399c13ab85067db4430b7c3b9c3`

The Python 3.14.7 tag was current on Docker Hub at the time of this audit and already
matches the repository's Python 3.14.7 compatibility jobs. The existing Trivy gate
remains authoritative: the replacement is accepted only if the final-head container
scan passes without weakening severity, fixability, or exit-code policy.

The 3.14.7 base removed the operating-system findings, but the next exact-head scan
still found two fixable HIGH Python-package findings: `msgpack 1.1.2` and
`setuptools 70.3.0`. Neither is an AI Workflow runtime dependency. They are packaging
surface brought into the final Python image. PR-27 therefore keeps build tooling in
the isolated build stage, installs the dependency-free AI Workflow wheel in the
runtime stage, and then removes runtime `msgpack`, `setuptools`, installed `pip`,
and `ensurepip`. A hermetic container contract test makes that reduction explicit.

This does not weaken the scanner or add an exception. The final image must still pass
the unchanged fixable HIGH/CRITICAL Trivy policy.

## Non-goals

PR-27 does not:

- change runtime routing, retrieval, ranking, budgets, authorization, or deployment;
- promote any experimental policy;
- claim publication-scale benchmark validity;
- claim that a passing test proves downstream patch correctness;
- replace the detailed research notes or benchmark reports.

## Acceptance criteria

- checked-in manifest validates;
- validator has negative tests for missing paths, unsupported promotion, missing
  benchmark evidence, and unknown research references;
- quality CI runs the validator;
- historical audit documentation points to the live manifest;
- README version label matches the package's existing `2.3.0` version source;
- the full existing CI/security/compatibility/benchmark matrix remains green.
