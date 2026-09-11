# Controlled contextual-policy deployment — Stage 7

Date: 2026-09-11

Stage 7 is the first AI Workflow stage that can send a learned contextual retrieval policy
a bounded fraction of real low-risk traffic.

The design goal is not autonomous rollout. The goal is controlled exposure with an explicit
production baseline, manually authorized stage transitions, live safety budgets, drift checks,
and automatic rollback.

## Research basis

### Agent Retrieval Bench

Bowen Qin and Yi Xie, *Agent Retrieval Bench: Evaluating Repository Context Retrieval for
Coding Agents*, arXiv:2607.24882.

https://arxiv.org/abs/2607.24882

ARB motivates context-dependent retrieval rather than one universal retrieval winner, but its
retrieval and seed-intervention results are not a license for unconstrained online deployment.
Stage 7 therefore continues to separate retrieval-policy evidence from downstream verified
outcomes.

### Staged rollout with sequential monitoring

Zhenyu Zhao, Mandie Liu and Anirban Deb, *Safely and Quickly Deploying New Features with a
Staged Rollout Framework Using Sequential Test and Adaptive Experimental Design*,
arXiv:1905.10493.

https://arxiv.org/abs/1905.10493

The paper describes gradual exposure, continuous regression monitoring, stopping a rollout when
degradation is detected, and increasing traffic after a stage clears its evaluation gate.

Stage 7 adopts that operational structure:

```text
approved 0%
  -> 1%
  -> 5%
  -> 10%
  -> bounded <= 25%
```

The exact Stage 7 percentages and exposure/failure budgets are implementation safety defaults.
They are not thresholds claimed by the paper.

### Google SRE canarying

Google's SRE workbook describes a canary as a partial, time-limited exposure that is evaluated
before proceeding with a wider rollout. Its core operational benefit is limiting the impact of a
defect while obtaining real-production evidence.

https://sre.google/workbook/canarying-releases/

Stage 7 keeps a baseline control and exposes only a randomized fraction of eligible low-risk
requests to the signed contextual candidate.

### Off-policy confidence sequences

Karampatziakis, Mineiro and Ramdas, *Off-policy Confidence Sequences*,
ICML 2021 / arXiv:2102.09540.

https://arxiv.org/abs/2102.09540

The paper develops confidence bounds that remain valid uniformly over time and explicitly
studies gated deployment.

Stage 7 reuses the conservative anytime-valid monitoring primitive introduced in Stage 6 for
live candidate-versus-control reward regression detection. It still does not claim to reproduce
the paper's tighter betting/martingale construction.

### Distribution shift

Si et al., *Distributionally Robust Policy Evaluation and Learning in Offline Contextual
Bandits*, ICML 2020.

https://proceedings.mlr.press/v119/si20a.html

Offline policy evaluation generally assumes that deployment resembles the historical data.
Real systems can experience covariate shift in contexts and concept/reward drift.

Stage 7 therefore treats these separately:

- context covariate drift: total-variation distance and unknown-context rate;
- reward/performance drift: candidate failure rate and sequential reward regression.

### Sequential risk constraints

Sun, Dey and Kapoor, *Safety-Aware Algorithms for Adversarial Contextual Bandit*,
ICML 2017.

https://proceedings.mlr.press/v70/sun17a.html

This work studies sequential decision making under cumulative risk constraints. Stage 7 does
not reproduce its algorithm, but adopts the operational principle that reward optimization alone
is insufficient: candidate exposure, failures and realized cost receive explicit cumulative
budgets.

## Trust chain

The deployment chain is:

```text
Stage 6 contextual report
  -> signed policy manifest
  -> verified zero-traffic shadow report
  -> explicit operator approval
  -> signed deployment state
  -> generation-checked transitions
  -> randomized live assignment
  -> verified delayed outcomes
  -> live guardrails
```

The same signing key authenticates the Stage 6 policy manifest and Stage 7 deployment state.

## Deployment state

Schema:

```text
retrieval-deployment-state-v1
```

The state contains:

- policy ID;
- embedded signed Stage 6 manifest;
- shadow-report digest;
- approval actor;
- stage;
- exact traffic fraction;
- generation;
- baseline context distribution;
- live guardrail configuration;
- rollback target;
- signed transition history.

Every state mutation increments the generation and rewrites the HMAC over the full state.

A stale operator command can provide `expected_generation`; if the state has changed since the
operator read it, the transition fails instead of overwriting the newer state.

Each successful state write also emits an immutable audit snapshot containing the state digest
and transition tail.

## Allowed transitions

Forward transitions are strictly sequential:

```text
approved -> canary_1 -> canary_5 -> canary_10 -> bounded
```

Any non-terminal stage can transition to:

```text
rolled_back
```

A rolled-back state cannot be promoted again. A new deployment approval is required.

The transition from `approved` to `canary_1` is explicitly manual.

Every transition after traffic has begun requires a guardrail report that:

- matches the policy ID;
- matches the current stage;
- matches the current generation;
- reports `safe_to_advance = true`.

The guardrail report's digest is recorded in signed deployment history.

## Runtime precedence

When `context.deployment.enabled = true`, Stage 7 becomes the behavior-policy controller.

Stage 5 epsilon exploration is not composed with Stage 7 canary assignment.

If deployment is disabled, Stage 5 behavior is unchanged.

If deployment is enabled but the signing key, state file, signature, schema, or traffic fraction
is invalid, the request fails closed to `adaptive_math`.

The existing `AI_WORKFLOW_LEARNING_KILL_SWITCH` also forces Stage 7 to the baseline.

## Risk boundary

Only low-risk requests may receive a non-baseline deployment arm.

```text
low risk       -> candidate/control canary eligible
medium risk    -> adaptive_math
high risk      -> adaptive_math
```

The policy still cannot learn or deploy changes to:

- risk classification;
- context ceilings;
- selector safety;
- sufficiency safety;
- early-stop safety.

## Randomized canary assignment

For an eligible low-risk context whose signed policy selects a non-baseline arm, Stage 7 draws a
fresh cryptographic nonce and derives a uniform bucket using HMAC-SHA256.

For traffic fraction p:

```text
candidate arm with probability p
adaptive_math with probability 1-p
```

The learning decision records:

- candidate probability;
- chosen probability;
- target arm;
- candidate/control assignment;
- deployment policy ID;
- stage;
- generation;
- context key;
- assignment nonce and bucket.

This makes the live randomized behavior policy explicit for later evaluation.

## Fail-closed logging

The Stage 5 rule still applies: a candidate action must be durably logged before it executes.

If candidate decision logging fails, retrieval falls back to `adaptive_math`. The fallback
record is relabeled as baseline and no longer counts as candidate exposure.

Control logging failure does not expose the candidate and therefore remains operationally safe,
although that event cannot contribute to later counterfactual evaluation.

## Cumulative safety budgets

Stage 7 ships with fixed conservative defaults:

| Stage | Candidate traffic | Cumulative candidate exposure budget | Candidate failure budget |
| --- | ---: | ---: | ---: |
| canary_1 | 1% | 100 | 5 |
| canary_5 | 5% | 500 | 20 |
| canary_10 | 10% | 1000 | 40 |
| bounded | <=25% | 5000 | 100 |

An optional cumulative realized-cost budget may also be specified when deployment state is
created.

These numbers are implementation defaults, not empirical guarantees from the research.

Exceeding an active hard budget requests automatic rollback.

## Failure-rate guardrail

After the configured minimum number of verified candidate outcomes, the deployment rolls back if
the candidate failure rate exceeds its configured maximum.

Verified outcomes come from the existing Stage 5 delayed-outcome contract. Missing success labels
are therefore not synthesized from retrieval proxies.

## Reward-regression guardrail

Candidate/control events retain their assignment probabilities.

For candidate event reward r and candidate probability p, the monitoring contribution is:

```text
+r / p
```

For a baseline-control event:

```text
-r / (1-p)
```

Stage 7 applies the Stage 6 conservative anytime-valid Hoeffding sequence to these bounded
importance-weighted differences.

The sequence is used as a harm detector. If enough monitored evidence exists and the upper
confidence bound falls below the configured negative regression margin, automatic rollback is
requested.

Stage advancement does not require this conservative interval to prove positive superiority
again. Stage 6 already supplied offline and independent shadow evidence. The live rollout gate
asks whether enough candidate outcomes exist and whether any rollback blocker is active.

## Covariate drift

When deployment state is approved, Stage 7 snapshots the recent low-risk context distribution
using the exact signed policy context fields.

During live traffic it measures:

```text
TV(P_live, P_baseline)
= 0.5 * sum_x |P_live(x) - P_baseline(x)|
```

It also measures the probability mass assigned to context keys absent from the signed policy.

After a minimum drift sample size, either excessive total-variation distance or excessive unknown
context rate requests rollback.

High/medium-risk traffic is excluded from this drift calculation because it can never receive a
candidate action.

## Automatic rollback

Before routing a live request, Stage 7 evaluates current verified deployment evidence.

If a hard guardrail requires rollback, the runtime attempts an atomic generation-checked signed
transition to `rolled_back`.

The rollback target is always `adaptive_math`.

If another process wins the state lock or changes the generation first, the current request still
fails closed to the baseline. A state-write race therefore cannot cause additional candidate
exposure on the request that observed the safety failure.

Enabled deployment configuration requires automatic rollback; disabling rollback while keeping
deployment enabled fails config validation.

## Manual rollout controls

Create approval:

```bash
ai-workflow deployment create \
  --manifest policy-manifest.json \
  --shadow-report shadow-report.json \
  --approved-by release-owner
```

Inspect state:

```bash
ai-workflow deployment status
```

Evaluate live guardrails:

```bash
ai-workflow deployment guardrails --output guardrails.json
```

Promote first traffic:

```bash
ai-workflow deployment promote \
  --to canary_1 \
  --actor release-owner \
  --expected-generation 1
```

Later promotion:

```bash
ai-workflow deployment promote \
  --to canary_5 \
  --actor release-owner \
  --expected-generation 2 \
  --guardrail-report guardrails.json
```

Rollback:

```bash
ai-workflow deployment rollback \
  --actor release-owner \
  --expected-generation 2 \
  --reason "manual safety stop"
```

## Explicit non-goals

Stage 7 does not:

- automatically promote to a wider traffic stage;
- exceed 25% candidate traffic;
- expose medium/high-risk requests;
- compose canary traffic with Stage 5 epsilon exploration;
- infer success from retrieval metrics;
- silently clip invalid importance weights;
- silently ignore context drift;
- reactivate a rolled-back deployment state.

## Stage 8 candidate

A later stage can focus on production hardening rather than widening autonomy: persistent
high-volume event storage, cluster-robust/sequential analysis for correlated workloads, signed
multi-approver promotion policy, external metrics adapters, and reproducible rollback incident
bundles. A 100% learned-policy rollout should remain a separate explicit decision rather than an
automatic consequence of Stage 7.
