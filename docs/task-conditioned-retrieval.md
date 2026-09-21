# Task-conditioned retrieval

AI Workflow adapts retrieval fusion to the workflow signal instead of using one
global ranking mixture for every coding task.

## Profiles

The policy is deterministic and code-owned. It recognizes the workflow families
used by Agent Retrieval Bench:

- `code2test`: test discovery after an implementation change
- `comment2context`: review feedback that needs surrounding context
- `trace2code`: stack traces and failure logs with strong lexical anchors
- `edit2ripple`: change-impact and blast-radius questions

Queries outside those families fall back to the existing exact, semantic, or
structural retrieval intent.

Each profile changes only the relative weights of source ranking, lexical BM25,
specialist retrieval, and (in adaptive mode) MMR relevance/diversity balance.
The existing RRF rank constant, provider availability, repository routing,
structural validation, evidence trust, and hard context budgets remain separate
controls.

## Trust boundary

Task classification cannot:

- enable a provider;
- add a repository to the PR-24 routing plan;
- create or approve a PR-23 repository-graph edge;
- promote evidence confidence or authority;
- increase hard token or character budgets;
- grant model/tool capabilities.

The chosen profile and weights are emitted in `policy_identity.task_retrieval_policy`
and `diagnostics.task_retrieval_policy` so a run can be audited and replayed.

## Research basis

The design follows the finding from Agent Retrieval Bench (arXiv:2607.24882)
that no single retrieval family dominates across code2test, comment2context,
trace2code, and edit2ripple tasks. AIRCoder (ACL 2026) independently supports
context-dependent fusion across textual, dependency, and structural signals,
while QuDAR (ACL 2026) shows the value of query-wise weighting over fixed global
hybrid weights.

This PR intentionally uses deterministic, training-free profiles. Learned policy
selection and calibration remain isolated behind the existing safe learning
framework rather than making model output authoritative.
