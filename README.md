# AI Workflow — Efficiency Control Plane

A thin, agent-agnostic control plane for AI-assisted software development.

It does **not** try to replace strong execution methodologies such as Superpowers or deep code-intelligence engines such as Code Review Graph (CRG). It decides **how much machinery a task deserves**, chooses the cheapest useful context source, enforces a context budget, coordinates execution, compresses noisy output, verifies completion, and stores reusable knowledge.

## Architecture

```text
                    AI Workflow
                Efficiency Control Plane

User task
   │
   ▼
Task + Risk Classifier
   │
   ├── Answer ───────────────► direct response
   │
   ├── Small ────────────────► lightweight execution
   │
   └── Full
        │
        ▼
   Execution Provider
   ├── Native
   └── Superpowers
        │
        ▼
   Context Broker
   ├── Hot cache
   ├── Lightweight indexes
   ├── Code Review Graph
   └── Targeted source fallback
        │
        ▼
   Context Budget
        │
        ▼
   Agent/model
        │
        ▼
   Output Compressor
        │
        ▼
   Verification
        │
        ▼
   Durable Memory
```

## What this project owns

- **Task + risk routing** — Answer / Small / Full lanes.
- **Provider selection** — native lightweight execution or Superpowers for rigorous Full-lane work.
- **Context brokering** — cache → local index → CRG → targeted source fallback.
- **Context budgeting** — hard estimated-token limits per lane so tools cannot flood the agent.
- **Cross-agent handoff** — compact, validated `.ai/HANDOFF.md`.
- **Output compression policy** — RTK when available, deterministic line/character caps otherwise.
- **Durable memory** — evidence-aware JSONL memories with source hashes and stale detection.
- **Verification + diagnostics** — `doctor`, handoff validation, index freshness, and unit tests.

## What it deliberately delegates

### Superpowers
Use Superpowers for high-rigor Full-lane execution when it is installed: planning, task decomposition, subagent execution, TDD/review loops, and model selection. AI Workflow supplies the task brief, bounded context, risk, invariants, and handoff rather than duplicating that methodology.

### Code Review Graph
Use CRG only when structural context is worth its overhead: callers/callees, tests-for, blast radius, execution flows, architecture, or multi-hop dependency questions. Simple symbol/route lookups remain on the local index path.

CRG is optional. The workflow still works without it.

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

### Existing PowerShell users

Compatibility wrappers remain under `ai-workspace/scripts/`:

```powershell
powershell -File ai-workspace/scripts/setup.ps1 -ProjectName "MyProject"
powershell -File ai-workspace/scripts/brief.ps1 -Query "add rate limiting to auth"
powershell -File ai-workspace/scripts/traverse.ps1 -Symbol UpdateRideState
```

## Main commands

```bash
ai-workflow init --project-name MyProject
ai-workflow route "task text"
ai-workflow brief "task text"
ai-workflow context "task text" --symbol Foo --endpoint /api/v1/foo
ai-workflow index
ai-workflow doctor
ai-workflow verify --check "python -m unittest discover -s tests -v" --strict
ai-workflow handoff validate
ai-workflow memory add --type decision --keywords "auth rate-limit" --summary "..."
ai-workflow memory search "auth rate-limit"
ai-workflow compress --file build.log --max-lines 80
ai-workflow benchmark --tasks benchmarks/sample-tasks.json
```

## Lane policy

| Lane | Typical use | Execution | Default context budget |
|---|---|---|---:|
| Answer | explanation, lookup, read-only question | direct | 1,200 est. tokens |
| Small | known low-risk edit, usually 1–2 files | native | 2,500 est. tokens |
| Full | multi-file, ambiguous, structural, or high-risk work | Superpowers when available, otherwise native | 6,000 est. tokens |

Security/payment/auth/schema/migration/concurrency/deploy/public-contract changes always escalate to Full unless configuration explicitly overrides them.

## Context broker

The broker queries sources in increasing-cost order:

1. `hot-cache.jsonl` / incident cache
2. `symbol-index.jsonl`, `endpoint-index.jsonl`, domain manifest, durable memory
3. Code Review Graph when the query is structural/multi-hop and CRG is installed
4. targeted source search (bounded `rg`, or Python fallback)

Every source receives a character allowance derived from the lane budget. Truncation is explicit.

## Agent / model tier

The control plane emits a provider-agnostic model tier instead of hard-coding vendor model names:

- `fast` — Answer and Small lanes
- `standard` — ordinary Full-lane work
- `capable` — high-risk Full-lane work

Superpowers can still choose different models per subtask internally; this tier is the default contract from the outer control plane.

## Superpowers integration

`ai-workflow brief` emits an execution-provider section. For a Full task with Superpowers detected, the recommended provider is `superpowers`, with `subagent-driven-development` preferred for an already-approved implementation plan and `executing-plans` as the sequential fallback.

The control plane does not vendor or silently install Superpowers. It detects it and produces a bounded execution contract. If your harness marketplace hides the install from filesystem detection, set `AI_WORKFLOW_SUPERPOWERS=1` or set `execution.superpowers.mode` to `on` in the control-plane config.

## Code Review Graph integration

If `code-review-graph` is on `PATH`, `doctor` reports it. Structural context requests can call its CLI wrappers (`query`, `impact`, `search`) when supported by the installed CRG version. Failures degrade safely to the next context source.

Example:

```bash
ai-workflow context "what can break if I change ProcessPayment" --symbol ProcessPayment
```

## Durable memory

Memories are stored in `ai-workspace/memory/memory.jsonl` with:

- stable id + type
- creation/verification timestamps
- keywords + summary
- evidence
- related files
- SHA-256 source hashes
- confidence

At recall time, memories whose referenced files changed are marked stale instead of being trusted silently.

## Configuration

Edit `ai-workspace/config/control-plane.json` to tune budgets, risk keywords, CRG escalation, result caps, and provider preferences.

## Design principles

- YAGNI: keep cheap tasks cheap.
- Indexes accelerate; source code remains truth.
- Optional tools must degrade safely.
- Never claim token savings without measurement.
- Keep stable global instructions small; put task-specific state in the handoff.
- Prefer deterministic local computation over sending raw data to an LLM.
- External/deploy/destructive writes require explicit approval.

## Verification

```bash
python -m unittest discover -s tests -v
python -m ai_workflow doctor --strict
```

## Benchmarking

`ai-workflow benchmark --tasks benchmarks/sample-tasks.json` measures the routing/context layer: selected lane/provider/model tier, context sources, estimated context tokens, budget utilization, and local broker latency.

The CLI reports **estimated context tokens** using a conservative character heuristic. This is not billed provider usage and the built-in benchmark does not prove task correctness. Provider tokens, output-filter savings, wall time, and task correctness should be measured separately when benchmarking real agents.
