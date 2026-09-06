# Architecture

## Control-plane pipeline

```text
Task
 → deterministic lane + risk classification (+ confidence)
 → choose execution provider + model tier
 → allocate hard lane context ceiling
 → classify retrieval intent
      ├─ exact      → local index + BM25
      ├─ semantic   → lexical + optional semantic provider
      ├─ structural → Code Review Graph when ready
      └─ mixed      → lexical + semantic
 → RRF fusion + MMR diversification where multiple rankings exist
 → evidence-sufficiency gate
 → adaptive context cap (hard lane ceiling is never exceeded)
 → targeted source fallback when evidence remains insufficient
 → agent/harness
 → compress noisy output
 → verify explicit checks + handoff
 → capture only verified durable memory
 → record mutation/full retrieval telemetry
```

## Key invariant

**Escalate capability, not context volume.** Stronger retrieval is selected because the query requires it, not because a model can accept more tokens.

## Deterministic safety boundary

High-risk mutation policy remains outside learned/semantic retrieval. Authentication, authorization, security, payments, billing, schema/migrations, concurrency, deployment, credentials, and public-contract changes deterministically escalate to Full/High. Routing confidence is diagnostic evidence; low confidence must never downgrade a hard safety rule.

## Retrieval intent

`ai_workflow.retrieval_policy` classifies retrieval separately from execution lane:

- **exact** — explicit symbol, endpoint, path, or identifier-shaped query.
- **semantic** — natural-language intent/paraphrase where exact vocabulary may differ from source.
- **structural** — callers, callees, tests-for, dependencies, impact, blast radius, architecture.
- **mixed** — exact and semantic evidence are both useful.

This avoids paying for dense retrieval before a graph query and avoids graph traversal for a simple symbol lookup.

## Evidence sufficiency and adaptive budgets

The lane budget remains a hard maximum. After the base retrieval stage, the controller evaluates lexical coverage, exact evidence, source diversity, and structural completeness. High-confidence evidence can reduce the delivered context to a configured fraction of the hard ceiling. Insufficient evidence may invoke semantic retrieval or source fallback.

The sufficiency score is a retrieval-control heuristic, not a correctness probability.

## Provider boundaries

### Native execution
Used for Answer and Small lanes, and as a Full-lane fallback. Native Full remains Plan → Build → Review.

### Superpowers
Preferred for Full-lane execution when detected. AI Workflow provides the task/risk/context contract and does not duplicate its methodology.

### Semantic provider
Optional command provider configured by `context.semantic.command` or `AI_WORKFLOW_SEMANTIC_CMD`. It receives one JSON request on stdin:

```json
{"query":"where do we prevent duplicate charges?","root":"/repo","limit":6}
```

It returns either a JSON array, `{ "items": [...] }`, or JSONL records containing `text`, optional `score`, and optional provenance such as `path`, `line`, or `sha256`. Failure, timeout, malformed output, or absence degrades to lexical/graph/source retrieval.

### Code Review Graph
Used for structural/multi-hop requests or broad/large-repository work when ready. One-hop symbol/route lookup stays local.

## Indexing

The index remains dependency-free. Python files use the standard-library AST to record function/class kind and end lines; syntax failures and non-Python languages fall back to the existing regex indexers. Per-file SHA-256 freshness remains authoritative.

## Context provenance and trust

Each selected context item carries provenance metadata. Repository-derived text is explicitly classified as untrusted repository content; generated/cache/memory context is marked separately. Retrieved text is evidence/data and must not be treated as executable agent instructions.

## Telemetry

Mutation and Full workflows can write atomic traces under `ai-workspace/generated/traces/` with retrieval intent, providers attempted/skipped, stage latency, candidate/selected counts, sufficiency, fallbacks, and context-budget use. Answer remains side-effect-free unless `--trace` is explicitly requested.

`ai-workflow stats` summarizes recent traces locally.

## Failure behavior

- Missing Superpowers → native execution.
- Missing/failed/timed-out semantic provider → lexical/graph/source retrieval.
- Missing/failed/timed-out CRG → bounded targeted source search.
- Stale local index → reject hit and continue.
- Stale memory → exclude from trusted context.
- Missing RTK → built-in deterministic compressor.

No optional provider may make the core workflow unavailable.
