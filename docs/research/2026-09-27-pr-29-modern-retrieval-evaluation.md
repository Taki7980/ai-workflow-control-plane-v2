# PR-29 — Modern retrieval evaluation

Date: 2026-09-27

## Problem

AI Workflow already measures file/span retrieval, selective controls, trajectory
exploration/utilization, frozen repository identity, and seed interventions.
Those are strong foundations, but the file-level evaluator still collapses all
relevant files into one binary set.

That hides an important distinction in modern coding-agent retrieval:

1. files that must be edited;
2. broader supporting context that helps the agent understand and complete the task;
3. plausible in-repository distractors that should not consume the context budget.

## Research basis refreshed 2026-09-27

### CORE-Bench (2026)

CORE-Bench frames code-agent retrieval as requirement-driven repository search and
separates:

- Level 2: issue-to-edit localization;
- Level 3: broader context retrieval.

It also highlights dense local distractors such as similar wrappers, adapters, and
configuration snippets. Its main evaluation reports nDCG and Recall over the
repository retrieval setting.

https://arxiv.org/abs/2606.11864

### ContextBench (2026)

ContextBench measures context retrieval as a process rather than only final patch
success, separating explored and utilized context and showing that agents often
favor recall over precision.

https://arxiv.org/abs/2602.05892

AI Workflow already has trajectory exploration/utilization metrics from this design
family, so PR-29 does not duplicate that layer.

### Agent Retrieval Bench (2026)

Agent Retrieval Bench evaluates upstream file retrieval on frozen repository
snapshots, reports file-level ranking metrics, selective controls, and demonstrates
that no single retrieval family dominates every task type.

https://arxiv.org/abs/2607.24882

PR-29 preserves those existing file-level metrics and adds role-aware evidence on
top of them.

## Design

Corpus cases may optionally add:

```json
{
  "gold_files": [
    "src/handler.py",
    "tests/test_handler.py"
  ],
  "file_relevance": [
    {"path": "src/handler.py", "role": "edit_target"},
    {
      "path": "tests/test_handler.py",
      "role": "supporting_context"
    }
  ],
  "distractor_files": [
    "src/legacy_handler.py"
  ]
}
```

When `file_relevance` is present, every `gold_files` entry must be labelled
exactly once. Known distractors must be repository-relative paths and cannot also
be gold files.

Roles are intentionally small and explicit:

- `edit_target`: file expected to require modification;
- `supporting_context`: useful auxiliary code/tests/docs/configuration.

## New metrics

For labelled cases the benchmark report adds:

- edit-target Recall@k;
- supporting-context Recall@k;
- edit-target MRR;
- weighted Recall@k;
- graded nDCG@k;
- useful Precision@k;
- known-distractor rate@k;
- coverage balance = min(edit recall, support recall) when both roles exist.

The graded relevance gain is:

```text
edit_target = 2
supporting_context = 1
other = 0
```

nDCG uses the standard exponential gain transform, so locating an edit target
early is worth more than locating support early while both remain relevant.

## Backward compatibility

Cases without `file_relevance` or `distractor_files` are unchanged. Existing
binary file metrics, span metrics, trajectory metrics, ablations, selective
controls, and intervention runners remain authoritative.

## What this does not claim

- Role labels do not prove downstream coding correctness.
- Supporting-context labels are only as trustworthy as their annotation source.
- Known-distractor rate measures labelled distractors, not every irrelevant file.
- Graded gains encode an evaluation convention, not a universal utility function.
- This PR does not change production retrieval/ranking behavior.

## Acceptance criteria

- role labels must cover every declared gold file exactly once;
- role labels accept only edit_target/supporting_context;
- distractor paths must be disjoint from gold paths;
- edit/support recall are reported separately;
- graded nDCG rewards edit-target-first ranking;
- known distractors are measured explicitly;
- benchmark summaries aggregate the new metrics;
- old benchmark inputs remain valid;
- capability evidence documents the limitation boundary;
- full CI/security/benchmark matrix is green before the PR is declared merge-ready.
