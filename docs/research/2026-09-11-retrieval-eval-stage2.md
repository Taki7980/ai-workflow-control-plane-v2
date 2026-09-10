# Retrieval evaluation stage 2 — 2026-09-11

Stage 1 made repository retrieval measurable against frozen commits, exact gold files,
selective no-gold controls, and wrong-repository cases. Stage 2 focuses on three remaining
process-level questions:

1. Which retrieval provider family is actually contributing quality?
2. Is a multi-repository case isolated to the repository it claims to evaluate?
3. Of the context an agent explores, what does it actually utilize?

## Research basis

### Agent Retrieval Bench — arXiv:2607.24882

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench reports that no single retrieval family dominates across repository
tasks. Lexical, embedding, and repository-map approaches win different metrics and task
families. It also evaluates logged context-selection trajectories and includes a controlled
seed-intervention pilot.

Stage 2 therefore adds explicit provider-family ablations and seed/explore/utilize trajectory
metrics rather than assuming the full adaptive stack is always better.

### ContextBench — arXiv:2602.05892

https://arxiv.org/abs/2602.05892

ContextBench evaluates context retrieval as an intermediate process and distinguishes
explored context from utilized context. The reported gap between those sets means recall
alone can reward wasteful agent behavior.

Stage 2 records separate exploration and utilization precision/recall, duplicate exploration,
and context-utilization rate.

### CORE-Bench — arXiv:2606.11864

https://arxiv.org/abs/2606.11864

CORE-Bench emphasizes repository-level retrieval under concrete repository state rather than
isolated snippet similarity. Stage 2 keeps per-case repository roots explicit and isolated so
multi-repository evaluation does not accidentally turn into a cross-repo retrieval benchmark.

## Multi-repository isolation

A case may declare:

```json
{
  "repository_path": "backend",
  "base_commit": "<frozen SHA>",
  "gold_files": ["internal/payment/service.go"]
}
```

The benchmark resolves `backend` under the benchmark root and runs retrieval from that
repository root. For the measured case only:

- legacy `workspace.roots` are cleared;
- `workspace.max_roots` is forced to 1;
- provider detection is performed against the selected repository;
- indexes, targeted search, semantic commands, CRG state, and workspace fingerprints are
  therefore scoped to that repository.

This prevents a sibling `frontend` or another repository in the parent folder from satisfying
the query accidentally.

This isolation applies to benchmark experiments only. Normal AI Workflow operation retains
its first-class multi-repository workspace behavior.

## Provider ablations

Use:

```bash
ai-workflow benchmark-ablate \
  --tasks benchmark-cases.json \
  --research-protocol \
  --require-frozen-snapshot
```

Available profiles:

| Profile | Native/base | Semantic | CRG | External retrievers |
| --- | --- | --- | --- | --- |
| `adaptive` | configured | configured | configured | configured |
| `base_only` | yes | off | off | off |
| `base_semantic` | yes | configured | off | off |
| `base_structural` | yes | off | configured | off |

The suite returns each full benchmark report plus deltas against `adaptive` for file-level
retrieval quality, selective-control accuracy, estimated context tokens, and latency.

These are provider-family ablations. They do not claim to isolate every ranking operation
inside the native broker; BM25/RRF/MMR or selector ablations should be added separately if
those algorithms need causal evaluation.

## Agent trajectory schema

A research case may include events inline:

```json
{
  "trajectory_events": [
    {"kind": "seed", "file": "src/payment.py", "step": 0},
    {"kind": "explored", "file": "src/payment.py", "step": 1},
    {"kind": "explored", "file": "src/noise.py", "step": 2},
    {"kind": "utilized", "file": "src/payment.py", "step": 3}
  ]
}
```

or reference a JSON/JSONL file relative to the benchmark root:

```json
{"trajectory_file": "trajectories/case-001.jsonl"}
```

Supported event kinds:

- `seed`: initial context supplied before agent exploration;
- `explored`: file opened/read/searched during the trajectory;
- `utilized`: file whose content materially entered reasoning, editing, or verification.

The benchmark reports:

- seed gold recall;
- exploration precision and recall;
- utilization precision and recall;
- context utilization rate;
- gold utilization rate;
- duplicate exploration rate;
- first gold exploration step;
- first gold utilization step;
- unique post-seed exploration.

## Interpretation

A better retriever should not be judged only by raw recall. Useful improvements should
normally move several signals together:

```text
higher gold-file recall
+ higher utilized-gold recall
+ higher context utilization
+ lower duplicate exploration
+ lower post-seed exploration
+ acceptable latency/token cost
```

If a profile increases retrieval recall while utilization precision collapses, it may simply be
feeding the agent more context.

If seed gold recall improves but post-seed exploration does not decrease, the downstream
agent may not be exploiting the retrieved context effectively.

## Next stage

After collecting enough real trajectories and a larger frozen multi-repository corpus:

1. add algorithm-level ablations for BM25, RRF, MMR, selector, and sufficiency gates;
2. add controlled retrieval-seed versus random-non-gold experiments;
3. add an oracle-gold seed mode to estimate remaining agent-side headroom;
4. stratify results by language, repository size, task type, and repo topology;
5. calibrate selective thresholds only on representative held-out natural no-gold data;
6. keep high-risk routing deterministic even if learned retrieval policies are introduced.
