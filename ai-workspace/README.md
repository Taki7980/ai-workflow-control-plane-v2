# AI Workspace

Runtime state and configuration for the AI Workflow Efficiency Control Plane.

- `config/control-plane.json` — routing, budget, provider, and context policy.
- `memory/memory.jsonl` — durable evidence-aware memory.
- `generated/` — rebuildable indexes, caches, and brief snapshots.
- `code-review-graph/` — per-repository CRG databases/artifacts managed by setup; runtime-only and gitignored.
- `agents/` — human/project conventions and domain routing hints.
- `scripts/` — PowerShell compatibility wrappers around the cross-platform Python CLI.

The Python package at repository root is the source of runtime behavior. PowerShell wrappers should stay thin to prevent rule drift.

A parent workspace does not need its own `.git`. `ai-workflow setup` discovers nested Git repositories/worktrees and keeps their shared control-plane state here instead of scattering AI Workflow state through each source repository.
