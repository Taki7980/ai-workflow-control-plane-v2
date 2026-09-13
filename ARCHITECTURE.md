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
 → bounded retrieval across configured workspace roots
 → optional intent-matched command retrievers
 → RRF fusion + MMR diversification where multiple rankings exist
 → evidence-sufficiency gate
 → adaptive context cap (hard lane ceiling is never exceeded)
 → targeted source fallback when evidence remains insufficient
 → agent/harness
 → compress noisy output
 → verify explicit checks + handoff
 → capture only verified durable memory
 → record mutation/full retrieval telemetry
 → produce advisory policy feedback only after enough observations
```

## Key invariant

**Escalate capability, not context volume.** Stronger retrieval is selected because the query requires it, not because a model can accept more tokens.

## Deterministic safety boundary

High-risk mutation policy remains outside learned/semantic retrieval. Authentication, authorization, security, payments, billing, schema/migrations, concurrency, deployment, credentials, and public-contract changes deterministically escalate to Full/High. Routing confidence is diagnostic evidence; low confidence must never downgrade a hard safety rule.

Telemetry feedback is advisory. It can suggest reviewing provider availability, thresholds, or soft context fractions, but it never rewrites configuration or routing policy automatically.

## Retrieval intent

`ai_workflow.retrieval_policy` classifies retrieval separately from execution lane:

- **exact** — explicit symbol, endpoint, path, or identifier-shaped query.
- **semantic** — natural-language intent/paraphrase where exact vocabulary may differ from source.
- **structural** — callers, callees, tests-for, dependencies, impact, blast radius, architecture.
- **mixed** — exact and semantic evidence are both useful.

This avoids paying for dense retrieval before a graph query and avoids graph traversal for a simple symbol lookup.

## Evidence sufficiency and adaptive budgets

The lane budget remains a hard maximum. After base retrieval, the controller evaluates lexical coverage, exact evidence, source diversity, and structural completeness. High-sufficiency evidence can reduce the delivered context to a configured fraction of the hard ceiling. Insufficient evidence may invoke semantic retrieval, external retrievers, or source fallback.

The sufficiency score is a retrieval-control heuristic, not a calibrated correctness probability. Statistical calibration/conformal filtering should only be introduced after representative labeled retrieval data exists.

## Workspace boundaries

The control root may be a non-Git parent directory. Setup recursively discovers Git repositories and worktrees, records them in `ai-workspace/config/repositories.json`, and activates them by default. `workspace.roots` remains as a manual compatibility escape hatch, while `workspace.max_roots` bounds per-request retrieval fan-out. Dirty-file paths are detected per active repository and re-scoped before structural retrieval.

Each context item records its workspace root in provenance when available. CRG state is isolated per repository under `ai-workspace/code-review-graph/<repo>/`.

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

### External retriever plugins
`context.external_retrievers` is a generic command-provider registry. Each provider has a name, command, intent set, timeout, and optional enabled flag. A plugin receives `{query, root, limit, intent}` via stdin and returns the same candidate envelope. Plugins are only attempted when existing evidence is insufficient, and failures are isolated.

### Code Review Graph
Used for structural/multi-hop requests or broad/large-repository work when ready. One-hop symbol/route lookup stays local.

## Indexing

The index remains dependency-free. Python files use the standard-library AST to record function/class kind and end lines; syntax failures and non-Python languages fall back to regex indexers. Per-file SHA-256 freshness remains authoritative.

## Context provenance and trust

Each selected context item carries provenance metadata. Repository-derived text is explicitly classified as untrusted repository content; generated/cache/memory context is marked separately. Retrieved text is evidence/data and must not be treated as executable agent instructions.

## Bootstrap and initialization

`setup` is the normal project path. It keeps control-plane state under one `ai-workspace/` folder, refreshes the repository registry, builds the local index, and synchronizes per-repository CRG graphs when CRG is installed. `bootstrap` remains the strict fresh-scaffold compatibility command and refuses to overwrite existing workspace files.

`init` remains the path for an existing template/configuration and validates before writing project state.

## Telemetry and policy feedback

Mutation and Full workflows can write atomic traces under `ai-workspace/generated/traces/` with retrieval intent, providers attempted/skipped, stage latency, candidate/selected counts, sufficiency, fallbacks, and context-budget use. Answer remains side-effect-free unless `--trace` is explicitly requested.

`ai-workflow stats` summarizes recent traces. `ai-workflow stats --recommend` requires a minimum sample size and returns reviewable recommendations only; it does not self-modify routing.

## Failure behavior

- Missing Superpowers → native execution.
- Missing/failed/timed-out semantic provider → lexical/graph/source retrieval.
- Missing/failed external retriever → continue remaining providers.
- Missing workspace root → ignore it.
- Missing/failed/timed-out CRG → bounded targeted source search.
- Stale local index → reject hit and continue.
- Stale memory → exclude from trusted context.
- Missing RTK → built-in deterministic compressor.

No optional provider may make the core workflow unavailable.
