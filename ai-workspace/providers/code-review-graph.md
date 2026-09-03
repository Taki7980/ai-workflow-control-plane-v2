# Code Review Graph Provider

CRG is optional. AI Workflow escalates to it for structural/multi-hop context such as callers/callees, tests-for, impact radius, flows, architecture, and refactors.

The adapter currently uses CRG's machine-readable CLI wrappers when available:
- `code-review-graph query --pattern <pattern> --target <symbol>`
- `code-review-graph impact --files <paths...>`
- `code-review-graph search --query <query> --limit <n>`

Any CRG error, timeout, missing graph, or unsupported installed version degrades safely to targeted source search. AI Workflow never treats CRG as the source of truth.
