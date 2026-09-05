# AI Workspace

Runtime state and configuration for the AI Workflow Efficiency Control Plane.

- `config/control-plane.json` — routing, budget, provider, and context policy.
- `memory/memory.jsonl` — durable evidence-aware memory.
- `generated/` — rebuildable indexes, caches, and brief snapshots.
- `agents/` — human/project conventions and domain routing hints.
- `scripts/` — PowerShell compatibility wrappers around the cross-platform Python CLI.

The Python package at repository root is the source of runtime behavior. PowerShell wrappers should stay thin to prevent rule drift.
