# Workflow Research Notes

## Current architecture decision

AI Workflow is an **efficiency control plane**, not a replacement for execution methodologies or code-intelligence engines.

- Superpowers: optional Full-lane execution provider.
- Code Review Graph: optional structural context provider.
- AI Workflow: lane/risk routing, context brokerage, budgets, handoffs, compression, verification, and durable cross-session memory.

## Constraints

- Keep cheap tasks cheap; avoid CRG/subagent overhead when local indexes or targeted source are enough.
- Treat indexes and memories as caches, not source of truth.
- Reject stale file-backed evidence using SHA-256.
- Keep context budgets explicit and loss-aware.
- Measure provider tokens, command-output reduction, wall time, and correctness separately.

## Upstream references checked for v2

- Superpowers subagent-driven development and plan execution: https://github.com/obra/superpowers
- Code Review Graph CLI/MCP and benchmark caveats: https://github.com/tirth8205/code-review-graph
