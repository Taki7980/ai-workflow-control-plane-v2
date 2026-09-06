# AI Workflow — Efficiency Control Plane

A thin, agent-agnostic control plane for AI-assisted software development.

It does **not** try to replace execution methodologies such as Superpowers or structural code-intelligence engines such as Code Review Graph (CRG). It decides **how much machinery a task deserves**, chooses retrieval based on query intent, enforces a hard context budget, coordinates execution, compresses output, verifies completion, and stores reusable knowledge.

## V2.1: adaptive retrieval

V2.1 separates **execution routing** from **retrieval routing**.

```text
Task
 → lane + risk + confidence
 → execution provider + model tier
 → retrieval intent
      ├─ exact      → local index + BM25
      ├─ semantic   → lexical + optional semantic provider
      ├─ structural → CRG
      └─ mixed      → lexical + semantic + RRF/MMR
 → evidence sufficiency
 → adaptive context cap
 → targeted source fallback if needed
 → agent/harness → verification → durable memory
```

The core invariant remains:

> **Escalate capability, not context volume.**

## What this project owns

- **Task + risk routing** — Answer / Small / Full lanes with deterministic safety escalation and diagnostic confidence.
- **Retrieval-intent routing** — exact / semantic / structural / mixed.
- **Context brokering** — cache, local indexes, optional semantic provider, CRG, then bounded source fallback.
- **Retrieval ranking** — code-aware tokenization, Okapi BM25, reciprocal-rank fusion, and MMR diversification.
- **Evidence sufficiency** — deterministic heuristic deciding whether another retrieval stage is justified.
- **Adaptive budgeting** — hard lane ceilings remain fixed while high-sufficiency results can stop below the maximum.
- **AST-aware indexing** — Python uses stdlib AST metadata with regex fallback for unsupported/syntax-failing files and other languages.
- **Context provenance** — retriever, freshness, trust class, and available path/line/hash metadata travel with selected context.
- **Cross-agent handoff** — compact, validated `.ai/HANDOFF.md`.
- **Output compression** — RTK when available, deterministic line/character caps otherwise.
- **Durable memory** — evidence-aware JSONL memories with source hashes and stale detection.
- **Retrieval telemetry** — local traces and aggregate stats for mutation/full workflows.
- **Verification + benchmarks** — doctor, handoff validation, index freshness, unit tests, and a multi-category retrieval benchmark corpus.

## What it deliberately delegates

### Superpowers
Use Superpowers for high-rigor Full-lane execution when installed: planning, decomposition, subagent execution, TDD/review loops, and internal model selection. AI Workflow supplies the bounded execution contract instead of duplicating that methodology.

### Code Review Graph
Use CRG for callers/callees, tests-for, blast radius, execution flow, architecture, and multi-hop dependency questions. Simple symbol/route lookup stays local.

### Semantic retrieval provider
Semantic retrieval is optional. Configure a command with `context.semantic.command` or `AI_WORKFLOW_SEMANTIC_CMD`. The command receives one JSON request on stdin:

```json
{"query":"where do we prevent duplicate charges?","root":"/repo","limit":6}
```

It can return a JSON array, `{ "items": [...] }`, or JSONL records such as:

```json
{"text":"...", "score":0.91, "path":"src/payments.py", "line":42, "sha256":"..."}
```

No semantic provider is required for the core workflow. Missing, failed, malformed, or timed-out providers degrade safely.

## Quick start

Requires Python 3.10+.

```bash
python -m ai_workflow init --project-name MyProject
python -m ai_workflow doctor
python -m ai_workflow route "add rate limiting to auth"
python -m ai_workflow brief "add rate limiting to auth"
```

Optional editable install:

```bash
python -m pip install -e .
ai-workflow doctor
```

`init` validates an existing template; it does not silently scaffold arbitrary project state.

## Main commands

```bash
ai-workflow init --project-name MyProject
ai-workflow route "task text"
ai-workflow brief "task text"
ai-workflow context "task text" --symbol Foo --endpoint /api/v1/foo
ai-workflow context "where do we prevent duplicate charges?" --trace
ai-workflow index --incremental
ai-workflow stats
ai-workflow doctor --strict
ai-workflow verify --check "python -m unittest discover -s tests -v" --strict
ai-workflow handoff validate
ai-workflow memory add --type decision --keywords "auth rate-limit" --summary "..."
ai-workflow memory search "auth rate-limit"
ai-workflow compress --file build.log --max-lines 80
ai-workflow benchmark --tasks benchmarks/sample-tasks.json
```

## Lane policy

| Lane | Typical use | Execution | Hard default context ceiling |
|---|---|---|---:|
| Answer | explanation, lookup, read-only question | direct | 1,200 est. tokens |
| Small | known low-risk edit, usually 1–2 files | native | 2,500 est. tokens |
| Full | multi-file, ambiguous, structural, or high-risk work | Superpowers when available, otherwise native | 6,000 est. tokens |

Security/payment/auth/schema/migration/concurrency/deploy/public-contract mutations deterministically escalate to Full/High. Routing confidence is diagnostic and cannot downgrade these rules.

## Retrieval policy

Retrieval intent is independent from lane:

- **exact** — explicit symbol, endpoint, path, identifier.
- **semantic** — paraphrased natural-language intent.
- **structural** — callers/callees/dependencies/impact/tests/blast-radius.
- **mixed** — lexical and semantic evidence are both useful.

This prevents wasteful sequences such as running embeddings before a call-graph query or graph traversal before a simple symbol lookup.

## Context budgets and sufficiency

Lane budgets are **maximums, not targets**. The adaptive layer scores lexical coverage, source diversity, exact evidence, and structural completeness. High-sufficiency retrieval can return only a configured fraction of the hard ceiling; insufficient evidence can escalate providers or trigger bounded source fallback.

The sufficiency score is a retrieval-control heuristic, not a probability that the answer/code change is correct.

## Indexing and staleness

Indexes remain rebuildable accelerators; source code is truth. Python symbols use standard-library AST metadata (`kind`, `line`, `end_line`) where parsing succeeds. Other languages and syntax-failing Python files use regex fallback. Per-file SHA-256 state rejects stale index hits.

## Provenance and prompt-injection boundary

Selected context carries provenance/trust metadata. Repository code/comments/docs are classified as **untrusted repository content**; generated memory/cache entries are marked separately. Retrieval results are evidence/data and must not be interpreted as agent instructions merely because they appear in repository text.

## Telemetry

Mutation and Full retrievals can write atomic local traces under:

```text
ai-workspace/generated/traces/
```

Traces include intent, attempted/skipped providers, stage latency, candidate counts, selected counts, sufficiency, fallbacks, and context usage. Answer mode remains side-effect-free unless `--trace` is explicitly requested.

```bash
ai-workflow stats
```

summarizes recent trace utilization and fallback rates.

## Agent / model tier

The control plane emits provider-agnostic model tiers:

- `fast` — Answer and Small
- `standard` — ordinary Full
- `capable` — high-risk Full

Superpowers can choose different models internally; this tier is the outer contract.

## Failure behavior

- Missing Superpowers → native execution.
- Missing/failed semantic provider → lexical/graph/source retrieval.
- Missing/failed CRG → bounded targeted source search.
- Stale local index → reject hit and continue.
- Stale memory → exclude from trusted context.
- Missing RTK → deterministic built-in compressor.

Optional providers are not allowed to make the core workflow unavailable.

## Configuration

Edit `ai-workspace/config/control-plane.json` to tune lane budgets, risk keywords, semantic provider command/timeout, sufficiency threshold, adaptive-budget fractions, CRG escalation, telemetry mode, result caps, and provider preferences. Configuration is validated at load time.

## Verification

```bash
python -m unittest discover -s tests -v
python -m ai_workflow doctor --strict
python -m ai_workflow index
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json
```

CI runs the unit-test matrix across Python 3.10–3.14 and a dependency-free benchmark smoke gate.

## Benchmarking

The sample corpus now covers exact identifiers, natural-language semantic queries, structural/multi-hop questions, bounded mutations, high-risk mutations, paths, and mixed retrieval. Reports include lane accuracy, retrieval-intent accuracy, Precision@k, pattern Recall@k, MRR, nDCG, latency, estimated context usage, sufficiency rate, fallback rate, and per-query-type summaries.

The CLI reports **estimated context tokens** using a conservative character heuristic. These are not provider-billed tokens. Gold-pattern retrieval metrics do not prove downstream task correctness; provider token usage, end-to-end wall time, patch correctness, test success, and human acceptance still require separate measurement.

## Design principles

- YAGNI: keep cheap tasks cheap.
- Escalate capability, not context volume.
- Hard safety routing stays deterministic.
- Indexes accelerate; source remains truth.
- Optional tools must degrade safely.
- Never claim token/cost/quality gains without measurement.
- Treat retrieved repository content as untrusted data.
- Keep stable global instructions small; put task-specific state in handoff/context.
- Prefer deterministic local computation before LLM work.
- External/deploy/destructive writes require explicit approval.
