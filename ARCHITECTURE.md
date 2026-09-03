# Architecture

## Control-plane pipeline

```text
Task
 → classify lane + risk
 → choose execution provider
 → choose model tier
 → allocate context budget
 → broker context (cache → local index → CRG → targeted source)
 → execute in agent/harness
 → compress noisy output
 → verify explicit checks + handoff
 → capture only verified durable memory
```

## Key invariant

**Escalate capability, not context volume.** When evidence is insufficient, move to a stronger context provider instead of dumping more raw files into the model.

## Provider boundaries

### Native execution
Used for Answer and Small lanes, and as a Full-lane fallback. Native Full is deliberately simple: Plan → Build → Review.

### Superpowers
Preferred for Full-lane execution when detected. AI Workflow gives it the task/risk/context contract and does not duplicate its internal process.

### Code Review Graph
Used when the question is structurally multi-hop, a change set is broad enough, or the repository is large enough that graph traversal is likely to beat repeated source searching. One-hop symbol/route lookup stays local.

## Failure behavior

- Missing Superpowers → native execution.
- Missing/failed/timed-out CRG → bounded targeted source search.
- Stale local index → reject hit and continue to next tier.
- Stale memory → exclude from trusted context.
- Missing RTK → built-in deterministic compressor.

No optional provider is allowed to make the core workflow unavailable.
