# PR-21 — CRG Semantic Golden Benchmark

Date: 2026-09-19

## Problem

Before PR-21, the real Code Review Graph integration test established that a
graph could be built, validated and queried for one simple Python caller
relationship. That is necessary but insufficient.

A structurally valid graph can still be semantically wrong on aliases,
ambiguous names, inheritance, callbacks, async control flow, test
relationships, language boundaries or incremental updates.

## Research basis

### Agent Retrieval Bench

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench evaluates repository context acquisition independently
from final patch generation, uses frozen base-commit repositories, and reports
retrieval metrics across code2test, comment2context, trace2code and
edit2ripple-style tasks. It finds that retrieval families trade off differently
across task types and that useful context can be missed even by successful
agent trajectories.

PR-21 adopts the upstream-evaluation principle: structural retrieval must be
measurable before downstream generation is considered.

### ContextBench

https://arxiv.org/abs/2602.05892

ContextBench uses human-annotated gold context and explicitly measures context
recall, precision and efficiency. Its results show a systematic tendency to
favor recall over precision and a gap between explored and utilized context.

PR-21 therefore reports both precision and recall rather than treating more
returned graph nodes as automatically better.

### CORE-Bench

https://arxiv.org/abs/2606.11864

CORE-Bench emphasizes that agentic code retrieval differs from isolated
docstring-to-function matching: agents must resolve repository-specific
symbols, edit locations and broader supporting context among realistic
distractors.

The duplicate-symbol and path-sensitive gold cases in PR-21 are designed around
that distinction.

### Code Review Graph's own benchmark protocol

https://github.com/tirth8205/code-review-graph/blob/main/docs/REPRODUCING.md

CRG's published multi-hop benchmark separates anchor discovery from neighbor
recall and reports honest misses. PR-21 follows the same principle: difficult
cases stay in the corpus, and the benchmark records a miss instead of deleting
or relabeling it.

### SCIP as future semantic reference

https://sourcegraph.com/docs/code-navigation/writing-an-indexer

SCIP occurrences carry semantic symbol identity and definition/reference roles
used for code navigation. PR-21 does not yet compare CRG against SCIP because
that is the explicit scope of PR-22. The corpus is structured so PR-22 can add
that differential oracle without replacing the PR-21 gold labels.

## Corpus design

The checked-in fixture is deliberately small enough to audit manually while
covering structural failure modes that a one-hop smoke test misses:

1. alias import;
2. duplicate symbol names;
3. inheritance/override;
4. callback passing;
5. async chain;
6. dynamic import;
7. generated code;
8. test relationship;
9. TypeScript call chain;
10. Go call chain.

Gold labels require both path and symbol substrings where ambiguity matters.

## Lifecycle controls

Semantic result quality is scored separately from graph-state safety.

The benchmark creates temporary Git repositories and measures:

- stale graph rejection after a source mutation without graph refresh;
- renamed/deleted symbol behavior after CRG incremental update;
- linked-worktree state isolation;
- same-symbol isolation between two repositories.

This keeps a stale-graph fail-closed success from artificially inflating
semantic recall.

## Metrics

For semantic cases:

- precision@K;
- recall@K;
- MRR;
- full-recall rate;
- category summaries.

For operating characteristics:

- query latency;
- p50/p95/p99 latency;
- estimated context tokens.

For graph lifecycle:

- lifecycle pass rate;
- stale-graph block rate.

## Baseline policy

The first CI execution of the completed corpus is used to establish the
measured baseline. The baseline is not chosen in advance.

Once recorded, CI must reject material regressions while still allowing the
known hard-case misses to remain visible. Improving a known miss should raise
the baseline in a deliberate follow-up change.

## Non-claims

This benchmark does not prove:

- compiler-level semantic precision;
- correctness for every CRG language;
- downstream patch correctness;
- SCIP agreement;
- source-grounded confidence calibration.

Those are outside PR-21. Differential SCIP/source validation is PR-22.
