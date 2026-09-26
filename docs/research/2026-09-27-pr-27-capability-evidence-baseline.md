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
