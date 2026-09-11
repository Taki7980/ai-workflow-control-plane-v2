# Benchmark Corpus v2 — Stage 9

Date: 2026-09-11

Stage 9 addresses the largest gap found in the research audit: AI Workflow had more
benchmark machinery than benchmark evidence.

## Research pressure

Agent Retrieval Bench evaluates 427 cases across 25 repositories with positive,
natural no-gold, and wrong-repository controls. It also freezes repository snapshots
and evaluates retrieval separately from downstream patch generation.

ContextBench expands repository-context evaluation to 1,136 tasks across 66
repositories and distinguishes explored from utilized context.

SWE-Explore moves the evaluation target from file-only localization toward line-level
coverage under fixed evidence budgets and reports a strong agentic-exploration tier.

CORE-Bench further shows that agentic repository retrieval remains materially harder
than traditional code search and that retrieval models still have adaptation headroom.

Primary references:

- https://arxiv.org/abs/2607.24882
- https://arxiv.org/abs/2602.05892
- https://arxiv.org/abs/2606.07297
- https://arxiv.org/abs/2606.11864

## What Stage 9 changes

### 1. Frozen contents, not only frozen HEAD

The old snapshot check only compared:

```text
git rev-parse HEAD == base_commit
```

That permits a dirty working tree to retain the expected commit.

Stage 9 captures:

- actual Git HEAD;
- porcelain dirty state, including untracked non-ignored files;
- SHA-256 of the canonical `git ls-tree -r -z HEAD` byte stream.

A strict case matches only when:

```text
head_match
AND worktree_clean
AND (
    no expected content manifest
    OR actual manifest == expected manifest
)
```

Schema-v2 research cases require an expected content manifest.

### 2. Span/line gold

Positive schema-v2 cases retain `gold_files` for compatibility and add
`gold_spans`.

Each span contains:

- repository ID when available;
- path;
- inclusive start/end lines;
- optional content SHA-256.

Retrieved line ranges are extracted from metadata/provenance, JSON index records, or
`path:start:end` textual evidence.

Stage 9 reports:

```text
span_precision_at_k
span_recall_at_k
span_f1
line_precision
line_recall
covered_gold_lines
first_gold_rank
```

### 3. Fixed evidence budgets

Corpus-v2 cases may specify `budget_tokens`. Benchmark execution then overrides the
normal lane token ceiling for that case only.

`budget_lines` constrains the span-scoring view. This makes line-level comparisons
possible without claiming that the runtime itself has become a line-based context
packer.

### 4. Control provenance

Schema-v2 selective controls cannot contain gold files/spans and require
`control_source`.

This does not magically certify naturalness. It makes the origin auditable and prevents
unlabelled synthetic strings from being silently treated as natural no-gold evidence.

### 5. Corpus/source provenance

A corpus-v2 document records:

- corpus ID;
- upstream source name/URL/license statement;
- split;
- cases.

Every v2 case records repository ID, language, label source, and labeler count.

The source registry under `benchmarks/corpus-v2/sources.json` intentionally links
primary datasets instead of vendoring them.

### 6. Persistent-project-knowledge isolation

Research-protocol runs explicitly exclude project-generated context channels:

- hot/incident caches;
- domain-manifest hints;
- research notes;
- durable memory.

Repository indexes, source search, configured structural retrieval, and explicitly
configured semantic/external retrieval remain available.

This prevents two confounders:

1. prior project knowledge leaking answers into a repository-retrieval benchmark;
2. read-time memory migration mutating an otherwise frozen benchmark worktree.

The legacy regression suite retains historical behavior for backward-compatible trend
tracking and is not used as publication-scale evidence.

### 7. Explicit readiness gate

A syntactically valid corpus is not necessarily research ready.

`benchmark-corpus validate --require-ready` currently requires at least:

- 427 cases;
- 25 repositories;
- 4 languages;
- natural no-gold controls;
- wrong-repository controls;
- span-labelled cases.

These are a floor preventing obviously tiny corpora from being represented as
publication-scale evidence. They are not a statistical guarantee of benchmark
validity.

## Why Stage 9 does not add 1,000 generated cases

The research audit recommended a future target near 1,000 cases / 50 repositories.
Generating labels automatically inside this PR would contaminate the evidence layer
and create an appearance of scale without trustworthy gold.

Stage 9 therefore builds:

```text
schema
+ clean snapshot identity
+ span evaluator
+ fixed budgets
+ source provenance
+ validation
+ readiness gate
+ CI research smoke
```

Actual corpus expansion remains a reproducible data-collection/annotation process.

## Threats still open after Stage 9

- The bundled legacy regression set is still self-repository and small.
- Real natural no-gold labels still need upstream/human provenance.
- Span gold from external corpora has not yet been materialized in this repository.
- Repository-group and chronological train/calibration/test splits belong to Stage 12.
- Multi-repository hierarchical retrieval quality is Stage 10.
- Line-level evaluation depends on retrievers emitting usable span metadata.

Stage 9 is therefore an evidence-contract upgrade, not a claim that empirical parity
with ARB/ContextBench/SWE-Explore has already been achieved.
