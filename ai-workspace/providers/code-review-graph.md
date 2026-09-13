# Code Review Graph Provider

CRG is optional. AI Workflow escalates to it for structural/multi-hop context such as callers/callees, tests-for, impact radius, flows, architecture, and refactors.

## Storage model

AI Workflow owns the workspace layout, while CRG owns the graph format. Every active Git repository gets an isolated CRG data directory:

```text
ai-workspace/
└─ code-review-graph/
   ├─ admin-panel/
   │  └─ graph.db
   └─ backend/
      └─ graph.db
```

The control root itself may be a non-Git parent. AI Workflow sets `CRG_DATA_DIR` and `CRG_REPO_ROOT` per repository, so CRG never needs a repo-local `.code-review-graph/` database for the managed workflow.

`ai-workflow setup` builds missing graphs and incrementally updates existing graphs when the `code-review-graph` executable is available. `ai-workflow doctor --strict` checks every active repository independently.

The runtime adapter continues to use CRG's CLI graph-query wrappers when available:
- `code-review-graph query ...`
- `code-review-graph impact ...`
- `code-review-graph search ...`

Any CRG error, timeout, missing graph, or unsupported installed version degrades safely to targeted source/semantic retrieval. AI Workflow never treats CRG as the source of truth.
