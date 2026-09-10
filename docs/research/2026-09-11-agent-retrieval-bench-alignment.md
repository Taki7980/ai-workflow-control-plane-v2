# Agent Retrieval Bench alignment — 2026-09-11

This note records the benchmark design changes motivated by **Agent Retrieval Bench**
(arXiv:2607.24882) and related repository-context evaluation work. The implementation
borrows evaluation principles, not reported scores.

## Why this exists

AI Workflow already routes exact, semantic, structural, and mixed retrieval; combines
heterogeneous evidence; enforces context budgets; and can abstain when evidence is
insufficient. The larger remaining gap was evaluation rigor.

Agent Retrieval Bench isolates repository context acquisition from final patch generation.
Its strongest design lessons for this project are:

1. evaluate against frozen base-commit repository states;
2. use file-level gold context rather than substring-only relevance;
3. separate task families such as code-to-test, comment-to-context, trace-to-code, and
   edit-ripple;
4. include natural no-gold and counterfactual wrong-repository controls;
5. report ranking quality and selective retrieval separately;
6. avoid treating a heuristic retrieval score as a calibrated probability.

ContextBench and CORE-Bench reinforce the need to measure context precision, recall,
efficiency, and repository-level localization directly rather than only downstream patch
success.

## Protocol fields

Research-protocol benchmark cases support:

- `task_type`: `code2test`, `comment2context`, `trace2code`, `edit2ripple`, or
  `no_gold`;
- `gold_files`: exact repository-relative file paths for positive cases;
- `base_commit`: full Git object ID for the frozen target state;
- `repository_path`: target repository path inside a multi-repo workspace;
- `control_type`: `positive`, `natural_no_gold`, or `wrong_repo`;
- `forbidden_repositories`: repository identities that must not contaminate a wrong-repo
  control;
- existing routing labels such as `expected_lane`, `expected_intent`, and
  `expected_evidence_state`.

Legacy benchmark files remain supported.

## New measurements

File-level positive cases report:

- Precision@k;
- Recall@k;
- MRR;
- nDCG@k;
- file F1;
- matched gold files per 1K estimated context tokens.

Selective controls report whether the evidence state matches the expected abstention or
exploration decision.

Wrong-repository controls additionally report repository-identity coverage and
contamination when retrievers provide repository provenance.

Every case reports frozen-snapshot state. For publishable experiments, run with both
`--research-protocol` and `--require-frozen-snapshot`.

## Recommended experiment layout

Do not benchmark a moving development checkout. Create a parent evaluation workspace with
one or more pinned repository worktrees or clones, install AI Workflow independently, and
run the benchmark from that parent root. This also exercises multi-repository isolation.

Example layout:

```text
retrieval-eval/
  repo-a/   # checked out at case base_commit
  repo-b/   # checked out at case base_commit
  benchmark-cases.json
```

A case then sets `repository_path` to `repo-a` or `repo-b`. Wrong-repository controls
can name the sibling repository identity in `forbidden_repositories`.

## What this does not claim

The bundled example is a schema/regression example, not a replication of Agent Retrieval
Bench. It does not reproduce that paper's dataset scale, human labels, embedding baselines,
logged agent trajectories, seed intervention, or oracle-context experiment.

Those are the next evidence milestones:

1. collect a multi-repository frozen corpus with exact file labels;
2. add realistic natural no-gold cases instead of only synthetic missing symbols;
3. add retriever ablations (lexical-only, semantic-only, structural-only, hybrid);
4. capture explored-versus-utilized context from agent trajectories;
5. run retrieval-seeded versus random-seed and oracle-gold experiments;
6. only then calibrate intent-specific abstention thresholds on held-out data.

## Sources

- Agent Retrieval Bench: https://arxiv.org/abs/2607.24882
- ContextBench: https://arxiv.org/abs/2602.05892
- CORE-Bench: https://arxiv.org/abs/2606.11864
