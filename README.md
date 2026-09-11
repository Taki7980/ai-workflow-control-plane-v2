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

Stage 5 adds an opt-in production learning foundation with logged behavior propensities and low-risk-only bounded exploration. It is disabled by default:

```json
{
  "context": {
    "learning": {
      "mode": "off",
      "kill_switch": false,
      "exploration_probability": 0.05,
      "allowed_risks": ["low"],
      "eligible_arms": [
        "adaptive_math",
        "source_rank",
        "bm25_rank",
        "rrf_only",
        "rrf_mmr_050",
        "rrf_mmr_075",
        "rrf_mmr_090"
      ]
    }
  }
}
```

Modes:

- `off`: no learning decision or learning record is emitted;
- `observe`: always use `adaptive_math`, but emit decision/observation records;
- `explore`: epsilon-style exploration across ranking-only arms, and only for low-risk tasks.

Medium/high-risk tasks always use `adaptive_math`. Safety-affecting Stage 3 profiles such as `selector_off`, `fixed_budget`, and `no_early_stop` cannot be configured as online exploration arms.

A process-wide emergency kill switch is always available:

```bash
AI_WORKFLOW_LEARNING_KILL_SWITCH=1 ai-workflow context "..."
```

Learning status:

```bash
ai-workflow learning status
```

Each active learning decision records the chosen arm, the full behavior-policy propensity vector, task fingerprint, lane/risk/intent, and a unique immutable decision ID before retrieval executes. If an exploratory action cannot be logged, AI Workflow fails closed to `adaptive_math`.

Retrieval observations are stored separately after execution. Verified outcomes may arrive later and are linked by decision ID:

```bash
ai-workflow learning record-outcome <decision-id> \
  --success \
  --source "verification-suite" \
  --reward 1.0 \
  --realized-cost 0.2
```

The outcome record preserves the original decision timestamp and verification delay.

Propensity-aware offline evaluation:

```bash
ai-workflow learning evaluate \
  --arm bm25_rank \
  --arm rrf_only \
  --confidence 0.95 \
  --resamples 5000 \
  --minimum-effective-sample-size 10 \
  --minimum-direct-exposures 5 \
  --safety-margin 0.0 \
  --max-realized-cost 1.0
```

The evaluator reports IPS and self-normalized importance weighting (SNIPS), overlap/coverage, effective sample size, maximum importance weight, realized costs, and a paired bootstrap reward/cost delta versus the `adaptive_math` baseline. A candidate is promotion-eligible only when support is sufficient, its reward lower bound clears the configured margin, and optional realized-cost constraints are satisfied.

Promotion remains advisory: `automatic_runtime_promotion` is always false in Stage 5. The evaluator explicitly reports that its bootstrap interval is not the exact Efron-Stein confidence bound from the confident-OPE paper.

Stage 6 adds contextual safe policy development on top of Stage 5 logs. New learning decisions carry a versioned categorical feature schema:

```text
retrieval-context-v1
  lane
  risk
  intent
  query_length_bucket
  changed_files_bucket
  workspace_roots_bucket
```

No task text or repository content is added to the feature record.

Develop a contextual policy with an independent holdout:

```bash
ai-workflow learning contextual-policy \
  --field intent \
  --field lane \
  --field changed_files_bucket \
  --development-fraction 0.7 \
  --minimum-context-events 10 \
  --minimum-direct-exposures 3 \
  --minimum-holdout-events 20 \
  --minimum-effective-sample-size 10 \
  --confidence 0.95 \
  --output contextual-policy.json
```

Stage 6 trains a smoothed categorical direct reward model on the development split, validates that model with deterministic cross-validation, freezes the resulting contextual policy, and evaluates it with doubly robust estimation on the untouched holdout. Non-low-risk rows always map to `adaptive_math`.

A policy that clears the holdout gates can be converted into a signed, shadow-only manifest. The HMAC key is supplied by an environment variable and is never written to the manifest:

```bash
export AI_WORKFLOW_POLICY_SIGNING_KEY="replace-with-a-real-secret"

ai-workflow learning create-manifest \
  --input contextual-policy.json \
  --output policy-manifest.json \
  --signing-key-env AI_WORKFLOW_POLICY_SIGNING_KEY

ai-workflow learning verify-manifest \
  --input policy-manifest.json \
  --signing-key-env AI_WORKFLOW_POLICY_SIGNING_KEY
```

The manifest contains a policy ID, feature-schema version, context mapping, source evidence digest, evidence cutoff, embedded fixed reward/cost models, locked risks, and explicit rollback target `adaptive_math`. It cannot request automatic runtime activation.

Shadow evaluation uses only verified outcomes recorded after the signed manifest's evidence cutoff:

```bash
ai-workflow learning shadow-evaluate \
  --manifest policy-manifest.json \
  --signing-key-env AI_WORKFLOW_POLICY_SIGNING_KEY \
  --confidence 0.95 \
  --reward-min 0 \
  --reward-max 1 \
  --max-importance-weight 20 \
  --minimum-new-events 20 \
  --safety-margin 0.0 \
  --output shadow-report.json
```

The shadow evaluator reports both held-fixed doubly robust diagnostics and an anytime-valid conservative Hoeffding confidence sequence for the post-cutoff reward difference. It blocks manual promotion review on manifest failure, missing target-policy support, importance-weight/range violations, insufficient new evidence, a non-positive anytime lower bound, or an optional realized-cost violation.

The Stage 6 confidence sequence is intentionally conservative and is not claimed to reproduce the exact betting/martingale construction from the Off-policy Confidence Sequences paper. Repeated calls recompute the same fixed-policy post-cutoff sequence, so checking again later does not turn an ordinary fixed-sample bootstrap interval into a deployment gate.

Stage 7 adds controlled real-traffic deployment. It is still disabled by default:

```json
{
  "context": {
    "deployment": {
      "enabled": false,
      "state_path": "ai-workspace/generated/learning/deployment/active.json",
      "signing_key_env": "AI_WORKFLOW_POLICY_SIGNING_KEY",
      "auto_rollback": true
    }
  }
}
```

When deployment is enabled, automatic rollback is mandatory. The existing `AI_WORKFLOW_LEARNING_KILL_SWITCH=1` emergency switch also forces Stage 7 back to `adaptive_math`.

Create a signed zero-traffic deployment state only after a Stage 6 signed manifest and passing shadow report exist:

```bash
ai-workflow deployment create \
  --manifest policy-manifest.json \
  --shadow-report shadow-report.json \
  --approved-by release-owner
```

The new state begins at:

```text
approved
traffic = 0%
```

Promotion is sequential:

```text
approved
  -> canary_1   (1%)
  -> canary_5   (5%)
  -> canary_10  (10%)
  -> bounded    (default 25%, hard maximum 25%)
```

The first 1% transition requires explicit operator action:

```bash
ai-workflow deployment promote \
  --to canary_1 \
  --actor release-owner \
  --expected-generation 1
```

Every later promotion requires a live guardrail report generated from the current state generation:

```bash
ai-workflow deployment guardrails --output guardrails.json

ai-workflow deployment promote \
  --to canary_5 \
  --actor release-owner \
  --expected-generation 2 \
  --guardrail-report guardrails.json
```

The same pattern is used for 10% and bounded traffic. A stale generation cannot overwrite newer deployment state.

For a low-risk context whose signed policy selects a non-baseline arm, Stage 7 performs a fresh randomized candidate/control assignment and records the exact candidate probability in the normal learning decision log. Stage 5 epsilon exploration does not mix with an active Stage 7 deployment. Medium/high-risk traffic and policy contexts mapped to the baseline remain on `adaptive_math`.

Live guardrails include:

- cumulative candidate exposure budget;
- cumulative candidate failure budget;
- optional cumulative realized-cost budget;
- candidate failure-rate limit;
- anytime reward-regression monitoring against the baseline control;
- context-distribution total-variation drift;
- unknown-context rate;
- malformed reward/propensity/context inputs.

The initial fixed candidate-exposure budgets are 100 / 500 / 1000 / 5000 across the 1% / 5% / 10% / bounded stages. The initial failure budgets are 5 / 20 / 40 / 100. These are conservative implementation defaults, not thresholds claimed by the cited research papers.

Stage advancement is a live non-regression gate: enough verified candidate outcomes must exist and no rollback blocker may be active. Stage 6 already established offline/shadow improvement evidence; Stage 7 does not require a 1% canary to prove superiority from scratch before it may advance.

If a hard guardrail trips, the runtime attempts an atomic signed transition to:

```text
rolled_back
traffic = 0%
rollback target = adaptive_math
```

Even if concurrent rollback state mutation cannot complete, the request that observed the failing guardrail still fails closed to the baseline.

Manual rollback is always available:

```bash
ai-workflow deployment rollback \
  --actor release-owner \
  --expected-generation 2 \
  --reason "manual safety stop"
```

A rolled-back deployment state is terminal. Reactivation requires creating a new approved deployment state rather than mutating the old rollback record.

Stage 8 hardens the rollout for production operation without increasing policy autonomy.

### Same-host WAL evidence mirror

Canonical immutable JSON decision, observation, and outcome records remain the safety source of truth. An optional SQLite WAL mirror can be enabled for higher-volume same-host querying and reconciliation:

```json
{
  "context": {
    "production": {
      "enabled": true,
      "sqlite_path": "ai-workspace/generated/learning/production/events.sqlite3",
      "busy_timeout_ms": 5000
    }
  }
}
```

Existing learning records can be backfilled idempotently:

```bash
ai-workflow production sync
ai-workflow production status
ai-workflow production reconcile
```

The mirror uses WAL mode, `synchronous=FULL`, a busy timeout, immutable event IDs, and SHA-256 payload digests. `reconcile` compares the SQLite mirror with the canonical JSON files and fails when canonical events are missing or have a different digest.

This SQLite mode is intentionally **same-host only**. SQLite WAL relies on shared-memory coordination and is not used as a multi-host/network-filesystem consensus mechanism.

### Crash-recoverable local rollout lock

Deployment-state mutation still uses a very small local critical section. Stage 8 adds owner metadata, a random ownership token, and bounded stale-lock recovery so a process crash cannot leave the rollout permanently locked.

This is a local-filesystem lock. It is not a distributed lock and does not claim cross-host mutual exclusion.

### Correlation-aware rollout diagnostics

Live rollout reports now include a cluster bootstrap grouped by `task_fingerprint`. Repeated observations of the same task fingerprint stay in the same resampled cluster instead of being treated as independent evidence.

Promotion requires both the normal verified-outcome minimum and a minimum number of task clusters. A confidently negative cluster-bootstrap upper bound can independently request rollback.

Defaults:

```text
minimum_monitor_clusters = 5
cluster_bootstrap_resamples = 2000
cluster_bootstrap_seed = 20260911
```

These are implementation defaults, not guarantees from the bootstrap literature.

### Low-cardinality observability snapshot

Export the current rollout metrics:

```bash
ai-workflow deployment metrics --output deployment-metrics.json
```

The Stage 8 export uses namespaced metric identifiers such as:

```text
ai_workflow.deployment.candidate.exposure
ai_workflow.deployment.candidate.failure_ratio
ai_workflow.deployment.context.tv_distance
ai_workflow.deployment.guardrail.rollback_required
ai_workflow.deployment.cluster.reward_difference
```

Only `policy_id` and rollout `stage` are exported as metric attributes. Per-request decision IDs, task fingerprints, repository paths, raw task text, and repository content are deliberately excluded.

The file is an observability interchange contract inspired by OpenTelemetry metric conventions; it is not a native OTLP exporter.

### Signed rollback incident bundles

Automatic and manual rollbacks can emit an immutable signed incident bundle under:

```text
ai-workspace/generated/learning/deployment/incidents/
```

The bundle contains state/guardrail digests, the rollout generation/stage, the rollback reason, aggregate evidence counts, outcome-source counts, and a short list of decision IDs for local investigation. It does not embed task text, repository content, environment variables, or the signing key.

Verify a bundle with:

```bash
ai-workflow deployment verify-incident \
  --input ai-workspace/generated/learning/deployment/incidents/<id>.json
```

Incident capture is secondary to rollback. A failed incident write never cancels or reverses a successful rollback.

Stage 8 deliberately does **not** add fake multi-approver controls. Real separation of duties requires independently authenticated actors/credentials; adding two strings to the same local command would not provide that property.

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
- `docs/research/2026-09-11-retrieval-learning-stage5.md`
- `docs/research/2026-09-11-contextual-learning-stage6.md`
- `docs/research/2026-09-11-controlled-deployment-stage7.md`
- `docs/research/2026-09-11-production-hardening-stage8.md`
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
