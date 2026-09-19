# CRG Semantic Golden Benchmark v1

This corpus evaluates structural correctness of the pinned
`code-review-graph==2.3.8` integration.

## Why this exists

A graph can be healthy, non-empty and fast while still returning the wrong
symbol relationship. This benchmark tests semantic behavior against explicit
gold expectations instead of treating successful graph construction as proof
of correctness.

The design follows current repository-context benchmark practice:

- frozen, reviewable fixture source;
- explicit gold relationships;
- per-case precision, recall and reciprocal rank;
- latency and estimated context cost;
- separate lifecycle controls for stale state and repository identity.

## Semantic cases

The fixture includes:

- import aliases;
- duplicate symbol names with path-sensitive gold labels;
- inheritance and overrides;
- callback passing;
- async call chains;
- dynamic imports;
- generated source;
- test relationships;
- TypeScript structural calls;
- Go structural calls.

Some cases are intentionally difficult. A miss remains a measured miss rather
than being removed from the corpus.

## Lifecycle controls

The runner separately validates:

- stale graph rejection after an unindexed source mutation;
- rename/delete behavior after an incremental graph update;
- linked Git worktree graph isolation;
- same-symbol isolation across two repositories.

## Metrics

The report includes:

- precision@K;
- recall@K;
- MRR;
- full-recall rate;
- mean query latency plus p50/p95/p99;
- estimated context tokens;
- lifecycle-control pass rate;
- stale-graph block rate;
- category-level summaries.

Token counts are estimates from the control-plane estimator, not provider-billed
tokens.

## Run locally

```bash
uv sync --locked --only-group crg
uv run --locked --no-sync python scripts/run_crg_semantic_benchmark.py \
  --output /tmp/crg-semantic-report.json
```

CI checks every report against the measured `baseline.json`. The baseline was
captured from the first successful full corpus run rather than chosen in
advance. It preserves known misses as visible benchmark debt while preventing
regression of the relationships CRG currently resolves correctly.

## Scope

PR-21 establishes the gold benchmark and regression signal.

PR-22 is responsible for differential validation against SCIP/source truth and
for evidence-confidence states. This benchmark does not claim CRG is compiler-
precise.
