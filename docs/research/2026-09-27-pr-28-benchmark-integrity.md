# PR-28 — Benchmark integrity and leakage prevention

Date: 2026-09-27

## Problem

The benchmark-v2 layer already pins base commits, tracked-content manifests, span gold,
fixed budgets, control provenance, and publication-readiness floors. Its Stage 9
research note explicitly left repository-group and chronological
development/calibration/test partitioning as future work.

That matters because a benchmark can be mechanically reproducible while still giving
an overly optimistic estimate if the same repository, task, or source instance appears
in both tuning and evaluation data.

## Current research basis

### Agent Retrieval Bench (2026)

Agent Retrieval Bench evaluates retrieval against frozen base-commit repositories and
separates retrieval quality from downstream patch generation. It also shows substantial
task-level variation between retrieval families and a calibration gap between
counterfactual controls and natural no-gold cases.

https://arxiv.org/abs/2607.24882

Implication for AI Workflow: frozen snapshots are necessary but not sufficient. Tuning
and final evaluation also need partition-level isolation.

### Repository-overlap controls in 2025–2026 research

Recent repository-grounded coding research increasingly excludes repositories that
overlap established benchmarks and deduplicates source-code overlap when constructing
evaluation sets. ICLR 2026 work on repository retrieval explicitly excludes
SWE-bench/LocBench repositories and performs near-identical repository deduplication.

Implication: repository identity is a first-class leakage boundary, not merely another
task field.

### SWE-bench contamination analyses

Recent analyses of SWE-bench-family evaluation report both answer/test weaknesses and
possible contamination effects. Other 2026 benchmark work recommends temporal controls
and cross-repository validation because repository familiarity can inflate apparent
coding ability.

Implication: AI Workflow should record source-event timing and repository isolation,
while avoiding claims that these metadata can prove what a proprietary model saw during
training.

### Private/held-out evaluation

SWE-Bench Pro uses public and private repository components specifically to preserve
evaluation integrity. The broader lesson is that final evaluation should not share the
same repositories used to design or calibrate the system.

## Design

PR-28 adds a cross-corpus integrity analyzer:

`ai_workflow/benchmark_integrity.py`

and exposes it as:

```bash
ai-workflow benchmark-corpus integrity \
  --input development.json \
  --input calibration.json \
  --input holdout.json
```

The report emits a canonical SHA-256 for every corpus document so experiment reports
can bind to the exact partition inputs.

### Hard blockers

- duplicate `case_id` across corpora;
- normalized task duplicates across protected split roles;
- the same repository/base/gold source instance across protected split roles;
- repository overlap between development, calibration, and holdout;
- malformed temporal provenance;
- a holdout case that is not bound to base-commit/content-manifest identity.

### Leakage signals

Some facts must be surfaced without pretending they are universally invalid:

- gold file paths/basenames appearing in task text;
- repository identity appearing in task text;
- highly similar task wording across protected splits;
- missing source-event time metadata;
- holdout data without an attestation that future Git history is inaccessible;
- an integrity run missing one or more protected split roles;
- custom split names that cannot be classified.

Real GitHub issues can legitimately mention a file or repository name, so these are
reported as visible signals. Callers can use `--fail-on-signals` when constructing a
strict hidden holdout.

## Split semantics

Recognized protected roles are:

- development;
- calibration;
- holdout.

Aliases such as `train`, `validation`, and `test` map to those roles. A corpus
may explicitly set `split_role` when its existing split name is domain-specific.

All three protected roles are repository-disjoint. This is intentionally stronger than
random task splitting because repository-level context, naming, layout, and conventions
can otherwise leak across tuning and final evaluation.

## What this does not claim

This PR does **not** claim that:

- repository-disjoint partitions prove absence of model pretraining contamination;
- a model's undocumented training cutoff can be inferred from benchmark metadata;
- file names in issue text are automatically cheating;
- the current bundled regression tasks become a publication-grade external benchmark;
- benchmark integrity alone establishes downstream coding correctness.

The gate protects evidence hygiene inside AI Workflow. It cannot observe proprietary
model training data.

For agent-executed holdouts, corpus metadata can attest `history_isolation` as
`git_metadata_removed`, `exported_tree`, or `sandboxed_no_history`. This is a
visible evidence claim, not enforcement by itself; the runner still has to make future
Git history inaccessible.

## Acceptance criteria

- clean development/calibration/holdout corpora produce a ready integrity report;
- repository overlap fails;
- task/source duplication across protected splits fails;
- duplicate case IDs fail;
- malformed temporal metadata fails;
- prompt gold/repository hints remain visible in the report;
- corpus digests are deterministic;
- CLI supports repeated `--input` and optional `--fail-on-signals`;
- capability evidence records the new integrity guard;
- all existing compatibility/security/benchmark/release smoke checks remain green.
