# Contextual safe policy learning — Stage 6

Date: 2026-09-11

Stage 6 moves AI Workflow from global safe-arm evaluation to context-dependent policy
development without allowing the learned policy to control production traffic.

The deterministic risk classifier remains above the learning system. Medium/high-risk
decisions always map to `adaptive_math`.

## Research basis

### Agent Retrieval Bench

Qin and Xie, *Agent Retrieval Bench: Evaluating Repository Context Retrieval for Coding
Agents*, arXiv:2607.24882.

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench reports that no retrieval family dominates across its task families.
That result argues against selecting one global winner. Stage 6 therefore introduces a
small, versioned contextual feature schema and learns a policy mapping contexts to safe
ranking arms.

ARB also warns against reading file-level retrieval quality as end-to-end patch success.
Stage 6 continues to require delayed verified outcomes from Stage 5 rather than using
retrieval scores as reward labels.

### Doubly Robust Policy Evaluation and Learning

Dudik, Langford and Li, *Doubly Robust Policy Evaluation and Learning*,
arXiv:1103.4601.

https://arxiv.org/abs/1103.4601

Doubly robust evaluation combines a direct reward model with logged behavior
propensities. The estimator can remain accurate when either the reward model or the
behavior-policy model is correct under the method's assumptions.

Stage 6 uses:

1. known behavior propensities logged by Stage 5;
2. a smoothed categorical direct model;
3. deterministic cross-validation of the direct model on the development split;
4. an untouched deterministic holdout for final contextual-policy DR evaluation.

This is intentionally simpler than fitting a neural or linear contextual learner. The goal
of Stage 6 is to make feature definitions, leakage boundaries, and deployment evidence
auditable before increasing model complexity.

## Stable feature schema

Every new learning decision records:

```text
feature_schema_version = retrieval-context-v1

lane
risk
intent
query_length_bucket
changed_files_bucket
workspace_roots_bucket
```

The feature schema stores categorical runtime metadata only.

It does not store:

- raw task text;
- source code;
- repository file names;
- retrieved chunks;
- embeddings.

Stage 5 records created before Stage 6 do not contain the schema version and are excluded
from contextual Stage 6 evaluation. They remain usable by the Stage 5 global IPS/SNIPS
evaluator.

## Policy-development split

Verified current-schema events are deterministically assigned to development or holdout
using SHA-256 of the immutable decision ID.

The development split is used for:

- direct reward/cost model fitting;
- cross-validation diagnostics;
- candidate context-to-arm mapping.

The holdout split is never used to choose the contextual mapping.

The report includes a digest of all source decision IDs and the maximum verified-outcome
timestamp used as the evidence cutoff.

## Direct model

For each context and action, the direct model estimates mean reward or realized cost.
Sparse context/action estimates are shrunk toward the action-level mean using a
configurable prior weight.

A context may select a non-baseline arm only when:

- the context has enough development events;
- that arm has enough direct development exposures in that context;
- its direct-model estimate clears the configured minimum estimated gain.

Otherwise the context maps to `adaptive_math`.

Non-low-risk rows are always baseline-mapped independently of the learned policy table.

## Held-out doubly robust evaluation

For holdout row i with context x, logged action a, reward r, behavior propensity p(a|x),
direct model q and fixed target action pi(x):

```text
DR_i(pi) =
  q(x, pi(x))
  + I[a = pi(x)] / p(a|x) * (r - q(x, a))
```

The policy report compares the contextual target policy against `adaptive_math` using
paired per-row DR reward and cost deltas.

A policy is only eligible to become a shadow candidate when all configured gates pass,
including:

- non-baseline contexts exist;
- holdout size is sufficient;
- effective sample size is sufficient;
- direct target exposures are sufficient;
- reward-model cross-validation has enough observations;
- the holdout DR reward lower confidence bound clears the safety margin;
- an optional realized-cost cap is satisfied.

Eligibility means **shadow candidate**, not production activation.

## Signed policy manifest

A qualifying report can be converted into
`retrieval-policy-manifest-v1`.

The manifest includes:

- immutable policy ID;
- feature schema version;
- context fields;
- fixed context-to-arm policy;
- baseline fallback;
- locked risks;
- evidence cutoff;
- source report SHA-256;
- source decision digest;
- fixed reward/cost models;
- holdout evidence;
- explicit rollback target.

The manifest is authenticated with HMAC-SHA256 using a key supplied by an environment
variable. The key is not persisted.

Verification checks:

- manifest schema;
- feature schema;
- policy ID;
- policy arm allowlist;
- HMAC;
- key ID;
- `shadow_only` status;
- medium/high risk locks;
- disabled automatic activation;
- rollback target `adaptive_math`.

## Independent post-cutoff shadow evaluation

Shadow evaluation never executes the candidate policy.

It evaluates the fixed signed policy only on verified outcomes whose recorded timestamp
is after the manifest evidence cutoff.

For each event, the target action must have positive support under the logged Stage 5
behavior policy. Any zero-support event blocks the gate instead of silently falling back
and pretending the target policy was evaluated.

The evaluator also reports fresh DR reward/cost diagnostics using the fixed models embedded
in the manifest.

## Repeated checks and confidence sequences

Ordinary fixed-sample confidence intervals are unsafe to repeatedly inspect until they
happen to cross a deployment threshold.

Karampatziakis, Mineiro and Ramdas, *Off-policy Confidence Sequences*,
arXiv:2102.09540, develops off-policy confidence bounds that are valid uniformly over time
and at arbitrary stopping times.

https://arxiv.org/abs/2102.09540

Stage 6 does **not** claim to reproduce that paper's exact martingale/betting construction.
Instead it implements a simpler conservative anytime-valid sequence using an explicit
union bound across time and Hoeffding bounds for bounded importance-weighted reward
differences.

The monitor requires:

- explicit reward bounds;
- an explicit maximum allowed importance weight;
- positive target-policy support.

If a relevant importance weight exceeds the configured maximum, the event is marked as a
monitoring violation and manual promotion review is blocked. The code does not clip the
event and then pretend the resulting estimate is unbiased.

The per-time error allocation is:

```text
alpha_t = alpha * 6 / (pi^2 * t^2)
```

Because the sum of `alpha_t` is at most `alpha`, applying Hoeffding at each time and a
union bound yields simultaneous coverage over all inspected times for the bounded
monitoring sequence.

This is intentionally conservative. Its role is a repeated-check deployment gate, not a
replacement for the richer off-policy confidence-sequence algorithms in the paper.

## Safe exploration baseline

Jagerman, Markov and de Rijke, *Safe Exploration for Optimizing Contextual Bandits*,
arXiv:2002.00467, starts from a production baseline and uses high-confidence off-policy
evidence before moving to a candidate policy.

https://arxiv.org/abs/2002.00467

Stage 6 preserves that architecture:

```text
deterministic safety layer
        |
        v
adaptive_math baseline
        |
        v
Stage 5 bounded low-risk logging/exploration
        |
        v
Stage 6 development split
        |
        v
contextual policy
        |
        v
independent DR holdout
        |
        v
signed shadow-only manifest
        |
        v
post-cutoff anytime-valid shadow gate
        |
        v
manual promotion review only
```

## Explicit non-goals

Stage 6 does not:

- activate a learned policy automatically;
- explore on medium/high-risk tasks;
- learn selector, context-budget, or early-stop safety controls;
- fit a neural contextual policy;
- reuse holdout data to choose the policy;
- treat Stage 5 pre-feature-schema data as contextual evidence;
- treat bootstrap confidence intervals as sequential deployment guarantees;
- claim exact implementation of Off-policy Confidence Sequences.

## Stage 7 candidate

A later stage can add a formally versioned promotion/rollback state machine and a
production shadow-routing mode that computes candidate actions online while still
executing the baseline. Only after enough signed post-cutoff evidence should the system
consider a canary policy with an explicit traffic ceiling and automatic rollback trigger.
