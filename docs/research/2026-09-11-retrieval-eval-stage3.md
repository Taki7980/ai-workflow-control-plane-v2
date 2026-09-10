# Retrieval evaluation stage 3 — 2026-09-11

Stage 3 turns retrieval evaluation from provider-family comparison into causal experiments on
the ranking and context-selection mechanisms themselves. It also adds a controlled
retrieval-seed intervention harness so downstream coding-agent behavior can be compared with
deterministic random non-gold and oracle-gold context.

## Research basis

### Agent Retrieval Bench — arXiv:2607.24882

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench reports task-dependent winners across lexical retrieval, repository-map
methods, and embedding retrievers. It also includes a controlled seed-intervention pilot:
retrieval-derived initial context improves file F1 and reduces post-seed exploration relative
to random non-gold context, while oracle gold context leaves substantial additional headroom.

The implication for AI Workflow is that the full adaptive stack should not be treated as one
indivisible algorithm. Ranking fusion, diversity, selection, early stopping, and context-budget
adaptation need independent measurements.

### ContextBench — arXiv:2602.05892

https://arxiv.org/abs/2602.05892

ContextBench distinguishes context explored by coding agents from context they ultimately
utilize. This makes downstream trajectory measurements important when interpreting a retrieval
gain: higher recall can be counterproductive if the agent explores more irrelevant files or
fails to use the useful context it received.

### Candidate-Constrained RAG — arXiv:2607.04008

https://arxiv.org/abs/2607.04008

Recent candidate-constrained RAG experiments combine deterministic provenance, lexical
retrieval, RRF, reranking, and late evidence selection, while showing that conclusions can
change across evaluation metrics. This reinforces using multi-metric ablations rather than
selecting an algorithm from a single aggregate score.

## Benchmark-only algorithm controls

Stage 3 introduces optional `context.experiments` settings consumed by the workflow engine.
They are not added to the default configuration and therefore do not alter production behavior
unless an experiment profile explicitly injects them.

Supported ranking modes:

- `adaptive`: preserve current production behavior;
- `source`: rank by provider/source score;
- `bm25`: rerank the candidate set by local BM25;
- `rrf`: combine source, lexical, and specialist rankings with reciprocal rank fusion;
- `rrf_mmr`: apply MMR diversity after RRF.

Experiment parameters:

- `rrf_k`: RRF rank constant;
- `mmr_lambda`: relevance/diversity tradeoff in [0, 1];
- `disable_early_sufficiency_gate`: force specialist escalation even when base evidence
  passes the early sufficiency threshold.

Every retrieval result exposes the active algorithm policy for auditability.

## Algorithm ablation profiles

`ai-workflow benchmark-algorithms` supports:

| Profile | Intervention |
| --- | --- |
| `adaptive_math` | unchanged production math |
| `source_rank` | provider/source score ordering |
| `bm25_rank` | BM25 ordering |
| `rrf_only` | RRF without MMR |
| `rrf_mmr_050` | RRF + MMR lambda 0.50 |
| `rrf_mmr_075` | RRF + MMR lambda 0.75 |
| `rrf_mmr_090` | RRF + MMR lambda 0.90 |
| `selector_off` | bypass budgeted context selector |
| `fixed_budget` | disable adaptive context shrinkage |
| `no_early_stop` | disable early sufficiency stopping |

The suite reports full benchmark results and deltas against `adaptive_math`. The explicit
0.75 profile exists so MMR parameter sensitivity can be compared without conflating it with
the production rule that skips hybrid reranking when no specialist evidence exists.

## Seed interventions

`ai-workflow benchmark-intervene` creates three seed conditions for positive gold-file cases:

### retrieval

Use the files actually selected by the current retrieval pipeline.

### random_non_gold

Select tracked repository files deterministically with SHA-256 using case identity as the key,
while excluding exact gold files. This provides a reproducible non-gold control rather than a
new random sample on every run.

### oracle_gold

Use exact annotated gold files, capped by `seed_k`. This estimates downstream agent headroom
when retrieval is no longer the bottleneck.

Seed manifests contain file-level precision, recall, and F1 before an agent is executed.

## External coding-agent runner protocol

The harness is vendor-neutral. An agent adapter is explicitly supplied with
`--runner-command`; AI Workflow never executes a benchmark runner implicitly.

The runner receives one JSON object on stdin:

```json
{
  "task": "fix payment reconciliation",
  "task_type": "edit2ripple",
  "repository_root": "/absolute/frozen/repo",
  "repository_path": "backend",
  "base_commit": "<sha>",
  "seed_mode": "retrieval",
  "seed_files": ["internal/payment/service.go"],
  "gold_files": ["internal/payment/service.go", "internal/payment/service_test.go"]
}
```

The runner returns:

```json
{
  "success": true,
  "trajectory_events": [
    {"kind": "explored", "file": "internal/payment/service.go", "step": 1},
    {"kind": "utilized", "file": "internal/payment/service.go", "step": 2}
  ],
  "metadata": {}
}
```

AI Workflow adds the seed events itself and computes the Stage-2 trajectory metrics.

Runner safety properties:

- no shell invocation;
- explicit argv;
- restricted inherited environment;
- optional explicit environment allowlist;
- per-run timeout;
- stdout spooled to a temporary file instead of unbounded in-memory capture;
- maximum accepted output bytes;
- stderr discarded by the benchmark harness;
- malformed output fails as a structured experiment error rather than becoming context.

## Controlled comparison

Completed trials are grouped by seed mode. The report includes:

- success rate when the adapter reports success;
- mean seed precision/recall/F1;
- exploration recall;
- utilization recall;
- context utilization;
- duplicate exploration;
- post-seed exploration.

For cases where both conditions complete, retrieval and oracle conditions also receive paired
metric deltas against `random_non_gold`. Paired comparison is preferable to comparing
unmatched global averages because repository/task difficulty is held constant within each pair.

## Interpreting Stage 3

Useful retrieval improvements should generally satisfy more than one condition:

```text
retrieval seed F1 > random seed F1
AND downstream utilization recall improves
AND post-seed exploration decreases or stays bounded
AND latency/context cost remains acceptable
```

If oracle gold context produces little improvement over normal retrieval, retrieval is probably
no longer the dominant bottleneck.

If oracle substantially outperforms retrieval, retrieval quality or context ranking still has
meaningful headroom.

If retrieval beats random at file metrics but does not improve downstream exploration or
success, the downstream agent is failing to exploit the provided context.

## Next stage

After enough real intervention runs exist, Stage 4 can add:

1. confidence intervals and paired bootstrap significance tests;
2. stratification by task type, language, repository size, and topology;
3. natural no-gold calibration on a held-out split;
4. threshold selection under explicit false-positive cost;
5. learned/bandit retrieval policy experiments using verified outcomes;
6. deterministic safety constraints that learned policies cannot override.
