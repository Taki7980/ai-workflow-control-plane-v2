# AI Workflow — Efficiency Control Plane

A dependency-free, agent-agnostic control plane for AI-assisted software development. It coordinates **Superpowers** for execution methodology and **Code Review Graph (CRG)** for structural code intelligence without reimplementing either system.

## V2.2

```text
Task
 → deterministic lane + risk + diagnostic confidence
 → retrieval intent: exact | semantic | structural | mixed
 → workspace-state fingerprint
 → local index / semantic providers / external retrievers / CRG
 → RRF fusion + MMR candidate diversification
 → evidence state: sufficient | requires_exploration | abstain
 → budgeted context assembly
      tight budget → relevance-first
      normal budget → facility-location greedy coverage
 → structural-complexity vector
 → conserved CRG / agent / review / verification budget
 → Superpowers execution contract
 → verification → durable memory → telemetry
```

Core invariant: **escalate capability, not context volume.**

## What V2.2 owns

- deterministic Answer / Small / Full routing and high-risk escalation;
- exact / semantic / structural / mixed retrieval routing;
- BM25, RRF and MMR candidate ranking;
- budget-constrained facility-location context assembly;
- explicit `sufficient`, `requires_exploration`, and `abstain` evidence states;
- optional semantic and generic command retrievers;
- optional bounded multi-root workspace retrieval;
- Python AST-aware indexing with regex fallback for other languages;
- SHA-256 stale-index and durable-memory rejection;
- workspace-state fingerprints tied to Git/index/changed-file state;
- provenance and trust metadata on selected context;
- CRG → Superpowers orchestration contracts with component-wise resource caps;
- local retrieval telemetry and advisory-only policy feedback;
- benchmark metrics for ranking quality, context density/yield, evidence state, and abstention.

It does **not** self-modify safety routing, require embeddings, or claim that a retrieval score is a calibrated probability of correctness.

## Superpowers + Code Review Graph

The roles are deliberately separate.

**CRG = structural intelligence.** For structural or mutation work, the emitted contract can request current MCP capabilities such as:

```text
get_minimal_context_tool
get_impact_radius_tool
query_graph_tool
get_review_context_tool
```

The exact plan is bounded by `execution.orchestration_budget.max_crg_calls` and graph depth. If CRG is unavailable, the workflow falls back to bounded source/semantic retrieval.

**Superpowers = software-engineering process.** When detected, V2.2 emits an ordered skill contract rather than duplicating Superpowers internals:

| Task | Superpowers contract |
|---|---|
| Answer | direct response |
| Small mutation | `test-driven-development` → `verification-before-completion` |
| Full mutation | `writing-plans` → `subagent-driven-development` → `requesting-code-review` → `verification-before-completion` |

If Superpowers is unavailable, native execution remains available.

`ai-workflow brief --format prompt` now emits the contract directly:

```text
[EVIDENCE_STATE] requires_exploration
[WORKSPACE_FINGERPRINT] ...
[SUPERPOWERS_SKILLS] writing-plans, subagent-driven-development, ...
[CRG_PLAN] get_minimal_context_tool, get_impact_radius_tool, ...
[AGENT_SLOTS] 3
```

A caller should not begin mutation while `EVIDENCE_STATE=requires_exploration`.

## Budgeted context selection

V2.2 treats context assembly as a budgeted coverage problem rather than blindly truncating the top-ranked list.

For candidate relevance `r_i` and code-aware token sets `T_i`:

```text
sim(i,j) = |T_i ∩ T_j| / |T_i ∪ T_j|
w_ij     = r_i · sim(i,j)
F(S)     = Σ_i max_{j∈S} w_ij
```

The normal-budget selector greedily maximizes marginal `F(S)` gain per character while respecting the hard context ceiling. Under very tight budgets it uses relevance-first selection. Mandatory CRG structural evidence is inserted first when available.

This is a deterministic lexical approximation inspired by submodular prompt-assembly research. It is not presented as embedding-equivalent semantic similarity.

## Evidence state

- `sufficient` — current evidence meets the retrieval-control threshold.
- `requires_exploration` — a mutation/structural task lacks enough evidence; investigate before editing.
- `abstain` — a read-only repository question lacks trustworthy supporting context; do not fabricate a repo-grounded answer.

The sufficiency score remains a heuristic. High-risk mutation rules are deterministic and cannot be downgraded by it.

## Workspace state

Each retrieval packet contains a stable fingerprint derived from:

- resolved project root;
- Git HEAD when available;
- index-state digest;
- changed-file identities and content hashes/states.

This lets downstream agents reject context that was built against a different workspace state.

Multi-root workspaces can be configured with:

```json
"workspace": {
  "roots": ["../backend", "../frontend"],
  "max_roots": 4
}
```

## Install

Requires Python 3.10+.

For normal use, install AI Workflow as an isolated command-line tool instead of adding it to your project's Python environment.

**Recommended — pipx:**

```bash
pipx install git+https://github.com/Taki7980/ai-workflow-control-plane-v2.git
```

**Alternative — uv:**

```bash
uv tool install git+https://github.com/Taki7980/ai-workflow-control-plane-v2.git
```

For local development of AI Workflow itself, an editable install remains appropriate:

```bash
python -m pip install -e .
```

## Quick start

From the project you want AI Workflow to manage:

```bash
cd path/to/your-project
ai-workflow setup
ai-workflow doctor --strict
ai-workflow brief "refactor payment retry handling" --format prompt
```

`setup` is safe to rerun. It creates only missing control-plane files, preserves an existing `AGENTS.md` and configuration, refreshes `.ai/PROJECT`, and builds the local index automatically. The project name defaults to the current directory name; use `--project-name NAME` only when you want a different display name.

For scripts or automation, request JSON explicitly:

```bash
ai-workflow setup --json
```

## Main commands

```bash
ai-workflow setup
ai-workflow setup --project-name MyProject
ai-workflow setup --json
ai-workflow bootstrap --project-name MyProject
ai-workflow init --project-name MyProject
ai-workflow route "task text"
ai-workflow brief "task text" --format json|markdown|prompt
ai-workflow context "task text" --symbol Foo --endpoint /api/v1/foo --trace
ai-workflow index --incremental
ai-workflow stats
ai-workflow stats --recommend --minimum-runs 20
ai-workflow doctor --strict
ai-workflow verify --check "python -m unittest discover -s tests -v" --strict
ai-workflow handoff validate
ai-workflow memory add --type decision --keywords "auth rate-limit" --summary "..."
ai-workflow memory search "auth rate-limit"
ai-workflow benchmark --tasks benchmarks/sample-tasks.json
```

`bootstrap` remains available as the strict compatibility command: unlike `setup`, it refuses to continue when control-plane files already exist.

## Lane and hard budget policy

| Lane | Typical use | Default context ceiling |
|---|---|---:|
| Answer | explanation / lookup | 1,200 est. tokens |
| Small | bounded low-risk mutation | 2,500 est. tokens |
| Full | ambiguous, structural, multi-file, or high-risk work | 6,000 est. tokens |

Auth/security/payment/schema/migration/concurrency/deploy/public-contract mutations deterministically escalate to Full/High.

## Optional retrievers

A semantic command provider can be configured with `context.semantic.command` or `AI_WORKFLOW_SEMANTIC_CMD`. Generic command retrievers can register for one or more intents through `context.external_retrievers`.

Providers receive JSON on stdin and return JSON/JSONL context candidates. Failure, timeout, malformed output, or absence must degrade safely to the remaining providers.

## Provenance and prompt-injection boundary

Selected context carries retriever, workspace, freshness, trust, and available path/line/hash metadata. Repository code/comments/docs are **untrusted repository content**. Retrieved text is evidence; it does not become agent instruction merely because it appears in the context packet.

## Telemetry and feedback

Mutation/Full workflows can write atomic local traces under `ai-workspace/generated/traces/`. `ai-workflow stats` summarizes provider usage, latency, context utilization and fallbacks.

`ai-workflow stats --recommend` generates reviewable recommendations only after a minimum sample count. It never changes deterministic safety rules or rewrites configuration automatically.

## Benchmarking

The built-in corpus contains exact, semantic, structural, mutation, high-risk, path, mixed, and no-gold controls. Metrics include:

- lane and retrieval-intent accuracy;
- evidence-state and read-only abstention accuracy;
- Precision@k, Recall@k, MRR, nDCG;
- relevant-item density;
- matched-pattern yield per 1K estimated context tokens;
- context utilization, sufficiency/fallback rate, and latency.

The research protocol also supports Agent Retrieval Bench-style `code2test`, `comment2context`, `trace2code`, `edit2ripple`, natural no-gold, and wrong-repository controls. Cases can declare exact `gold_files`, a frozen `base_commit`, and a `repository_path`; results add file-level Precision/Recall/MRR/nDCG/F1, frozen-snapshot status, selective-control accuracy, and wrong-repository contamination diagnostics when repository identity is available.

```bash
ai-workflow benchmark \
  --tasks benchmarks/research-protocol-example.json \
  --research-protocol
```

The bundled file demonstrates the schema against a historical frozen commit, so its snapshot may intentionally report a mismatch on newer checkouts. For publishable/reproducible runs, point cases at pinned target clones/worktrees and add `--require-frozen-snapshot`. The legacy corpus remains backward-compatible for fast regression checks.

For multi-repository evaluations, set `repository_path` on each case. The benchmark runner resolves that repository as the case root and forces `workspace.max_roots=1` with legacy workspace roots cleared for the run, preventing sibling repositories from leaking into the measured context.

Compare provider families on exactly the same cases with:

```bash
ai-workflow benchmark-ablate \
  --tasks benchmarks/research-protocol-example.json \
  --profile adaptive \
  --profile base_only \
  --profile base_semantic \
  --profile base_structural
```

The ablation profiles intentionally measure provider-family contribution: `base_only` disables semantic, external, and CRG retrieval; `base_semantic` keeps the configured semantic provider but disables CRG/external retrievers; `base_structural` keeps CRG but disables semantic/external retrievers; `adaptive` preserves normal policy.

Research cases may also provide `trajectory_events` inline or a benchmark-root-relative `trajectory_file`. Events use `kind: seed|explored|utilized`, `file`, and `step`. Reports then separate exploration precision/recall from utilization precision/recall, duplicate exploration, seed gold recall, and post-seed exploration.

Stage 3 can isolate ranking and context-selection algorithms while preserving production defaults:

```bash
ai-workflow benchmark-algorithms \
  --tasks benchmarks/research-protocol-example.json \
  --profile adaptive_math \
  --profile bm25_rank \
  --profile rrf_only \
  --profile rrf_mmr_075 \
  --profile selector_off \
  --profile no_early_stop
```

Available profiles cover provider-score ordering, BM25 ordering, RRF without MMR, MMR sensitivity at 0.50/0.75/0.90, selector removal, fixed context budgets, and early-sufficiency-gate removal. The active algorithm policy is written into every benchmark case result.

Controlled seed interventions compare retrieved context with a deterministic non-gold baseline and oracle gold context:

```bash
ai-workflow benchmark-intervene \
  --tasks benchmarks/research-protocol-example.json \
  --mode retrieval \
  --mode random_non_gold \
  --mode oracle_gold \
  --seed-k 5 \
  --output seed-manifest.json
```

Without a runner command this creates a reproducible intervention manifest. To execute real coding-agent trials, provide an explicit runner executable:

```bash
ai-workflow benchmark-intervene \
  --tasks benchmark-cases.json \
  --research-protocol \
  --require-frozen-snapshot \
  --runner-command python \
  --runner-arg scripts/my_agent_runner.py
```

The runner receives one JSON object on stdin containing the task, frozen repository root, seed mode, seed files, and gold files. It returns one JSON object with optional `success: true|false` and `trajectory_events`. Runner subprocesses use no shell, a restricted environment, a timeout, and disk-spooled bounded stdout. Results include paired deltas against `random_non_gold`.

Stage 4 adds statistical confidence and calibration without allowing experiments to change runtime behavior:

```bash
ai-workflow benchmark-statistics \
  --input seed-run.json \
  --confidence 0.95 \
  --resamples 5000 \
  --stratify task_type \
  --output seed-stats.json
```

This computes deterministic paired bootstrap confidence intervals, win/tie/loss counts, win rates, and paired effect sizes against the `random_non_gold` condition. Stratification supports fields such as `task_type` or `repository_path`.

Sufficiency thresholds can be evaluated on a deterministic held-out split:

```bash
ai-workflow benchmark-calibrate \
  --input benchmark-report.json \
  --calibration-fraction 0.7 \
  --false-accept-cost 5 \
  --false-reject-cost 1 \
  --output calibration.json
```

The selected threshold minimizes explicit misclassification cost on the calibration split and is then reported separately on holdout cases. The result is always `advisory_only`; it is never written into production configuration automatically.

Stage 3 algorithm reports can also feed the conservative policy advisor:

```bash
ai-workflow benchmark-policy-advisor \
  --input algorithm-report.json \
  --context-field task_type \
  --minimum-samples 10 \
  --confidence 0.95 \
  --safety-margin 0.0 \
  --output policy-advice.json
```

A candidate algorithm is recommended only when its paired bootstrap lower confidence bound clears the configured safety margin versus `adaptive_math`. High/critical-risk cases are excluded from learning and remain baseline-locked. The advisor does not perform online bandit actions and explicitly refuses off-policy claims until randomized logging or action propensities exist.

These are routing/retrieval metrics. They do not prove downstream patch correctness or billed-token savings.

## Verification

```bash
python -m unittest discover -s tests -v
python -m ai_workflow doctor --strict
python -m ai_workflow index
python -m ai_workflow benchmark --tasks benchmarks/sample-tasks.json
```

CI runs Python 3.10–3.14 on Linux, Python 3.14 on Windows, and the V2.2 benchmark smoke gate.

## Research

Research/design rationale and formulas are documented in:

- `docs/research/2026-adaptive-retrieval.md`
- `docs/research/2026-09-07-v22-research.md`
- `docs/research/2026-09-11-agent-retrieval-bench-alignment.md`
- `docs/research/2026-09-11-retrieval-eval-stage2.md`
- `docs/research/2026-09-11-retrieval-eval-stage3.md`
- `docs/research/2026-09-11-retrieval-eval-stage4.md`
- `docs/superpowers/specs/2026-09-07-v22-agentic-orchestration-design.md`

## Design principles

- keep cheap tasks cheap;
- source code remains truth;
- use graph structure for structural questions, not everything;
- hard safety rules remain deterministic;
- context budgets are ceilings, not targets;
- prefer measurable evidence over claimed token savings;
- optional integrations must degrade safely;
- retrieved repository text is untrusted data;
- learning from telemetry is advisory until verified outcome data justifies stronger adaptation.
