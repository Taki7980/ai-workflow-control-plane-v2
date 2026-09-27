# PR-30 — Context efficiency and token economics

Date: 2026-09-28

## Problem

AI Workflow already enforces hard context budgets and reports selected context
size, retrieval quality, latency, and trajectory utilization. However, those
signals do not expose the full context-cost funnel.

A benchmark can therefore look efficient because the final context is small
while hiding expensive upstream retrieval, duplicate evidence, or low-value
selected context.

PR-30 makes that cost visible without changing production retrieval behavior.

## Research basis refreshed 2026-09-28

### What Context Does a Coding Agent Actually Need to Act? (2026)

This coding-agent study holds localization fixed and varies only the context
representation on SWE-bench Verified. It reports that compressed edit-local
context can match whole-file context at substantially lower context-token cost.

https://arxiv.org/abs/2607.09691

### Tokenomics: Quantifying Where Tokens Are Used in Agentic Software Engineering (2026)

This work instruments software-engineering agent traces and finds that input
tokens make up the largest token share on average, motivating stage-level token
accounting rather than reporting only task success.

https://arxiv.org/abs/2601.14470

### Dynamic Context Selection for RAG (2025)

This work studies the downside of fixed top-k retrieval and motivates
query-specific context sizing to reduce distractors rather than blindly filling
a context window.

https://arxiv.org/abs/2512.14313

AI Workflow already has adaptive budgets and a token-aware selector. PR-30 does
not replace them. It adds evidence needed to test whether they are actually
efficient.

## Design

Every detailed retrieval run receives a provider-neutral estimated-token funnel:

```text
provider retrieval
  -> raw retrieved items/tokens
  -> exact-deduplicated items/tokens
  -> ranked candidate items/tokens
  -> selected items/tokens
```

The funnel records:

- raw retrieved items and estimated tokens;
- exact-deduplicated items and estimated tokens;
- duplicate items/tokens avoided before context assembly;
- ranked candidate items/tokens;
- selected items/tokens;
- selected/retrieved and selected/ranked ratios;
- estimated token reduction versus raw retrieval;
- hard/adaptive budget utilization;
- retrieval-call count.

The benchmark then adds label-aware selected-token accounting:

- selected gold-file estimated tokens;
- selected edit-target estimated tokens;
- selected supporting-context estimated tokens;
- selected known-distractor estimated tokens;
- selected unattributed estimated tokens;
- token-share metrics for each class;
- gold-file token yield per 1K retrieved estimated tokens;
- end-to-end retrieval latency.

These are aggregated globally and by task/query type.

## Interpretation

The new metrics answer different questions:

- **duplicate token fraction**: how much raw retrieval was exact repetition?
- **selected/retrieved ratio**: how aggressively did the pipeline compress?
- **gold-file token share**: how much selected context came from labelled gold files?
- **known-distractor token share**: how much selected budget was spent on labelled decoys?
- **gold tokens / 1K retrieved**: how much labelled gold context survives per unit of retrieval volume?
- **retrieval-call count + latency**: did lower final context merely move cost upstream?

## Important limitations

- All token counts are provider-neutral estimates, not provider-billed tokens.
- No dollar-cost claim is made because provider pricing, caching, reasoning
  tokens, and billing rules vary over time and by model.
- Gold-file token share counts selected text from a labelled gold file; it does
  not prove every token from that file was necessary.
- Duplicate accounting is exact-content deduplication only.
- Token efficiency does not prove downstream coding correctness.
- Existing seed-intervention experiments remain the causal bridge between
  retrieval context and downstream task success.

## Acceptance criteria

- exact duplicate retrieval is visible in item/token accounting;
- ranked and selected token volumes are separately visible;
- hard/adaptive budget utilization is reported;
- benchmark cases report gold/edit/support/distractor token shares when labels
  exist;
- retrieval call count and latency are included;
- algorithm ablation reports compare the new efficiency metrics;
- existing benchmark inputs remain backward compatible;
- no production ranking/routing/safety behavior changes;
- full CI/security/benchmark matrix must pass before the PR is declared
  merge-ready.
