# Migration to v2 — Efficiency Control Plane

## What changed

v1 bundled orchestration, navigation, memory, and output guidance mostly inside PowerShell scripts and `AGENTS.md`.

v2 separates responsibilities:

- **AI Workflow owns:** routing, risk, budgets, provider selection, context brokerage, handoff, compression, verification, durable memory.
- **Superpowers may own:** Full-lane planning/execution/subagents/TDD/review methodology.
- **Code Review Graph may own:** deep structural code intelligence.
- **Source/tests remain truth.** All caches/indexes are optional acceleration structures.

## Compatibility

The old PowerShell command names remain under `ai-workspace/scripts/`, but most are now thin wrappers around `python -m ai_workflow`. This prevents separate PowerShell and Python implementations from drifting.

`generate-diff-brief.ps1` had bootstrap behavior despite its name in v1. In v2 it is an explicit deprecated alias to `setup.ps1`.

## First run

```bash
python -m ai_workflow init --project-name MyProject
python -m ai_workflow doctor --strict
```

Then optionally install/configure Superpowers and Code Review Graph in the coding harnesses that should use them.

## Memory migration

The old Markdown brain files are retained as compatibility markers. New machine memories go to `ai-workspace/memory/memory.jsonl` and can carry file hashes so stale memories are rejected.

Migrate only verified, reusable old entries; do not blindly copy historical transcripts.
