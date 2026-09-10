# Retrieval learning stage 5 — 2026-09-11

Stage 5 adds the minimum production-learning substrate required before AI Workflow can make
statistically meaningful adaptive retrieval decisions.

It does not automatically promote learned policies. The production baseline remains
`adaptive_math`, and online exploration is opt-in, bounded, low-risk only, and immediately
killable.

## Research basis

### Agent Retrieval Bench — arXiv:2607.24882

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench shows that repository-retrieval performance is task-dependent: no single
retrieval family dominates across code2test, comment2context, trace2code, and edit2ripple.
Its seed-intervention pilot also shows that better initial retrieval can improve file F1 and
reduce subsequent exploration while oracle context leaves meaningful headroom.

The production implication is not "pick the globally best retriever." The system needs a way
to learn which safe retrieval ranking works best for a context while preserving a deterministic
baseline.

### Safe Exploration for Optimizing Contextual Bandits — arXiv:2002.00467

https://arxiv.org/abs/2002.00467

Safe Exploration Algorithm (SEA) starts from a production baseline, learns from logged behavior,
and only moves toward a candidate policy after high-confidence off-policy evaluation indicates
that the new policy is at least as good as the baseline.

Stage 5 mirrors that structure:

1. `adaptive_math` is the baseline;
2. online exploration is bounded;
3. behavior propensities are logged before action execution;
4. high-risk contexts never enter the exploration action set;
5. candidate policy promotion is advisory and confidence-gated.

### Confident Off-Policy Evaluation and Selection through Self-Normalized Importance Weighting — arXiv:2006.10460

https://arxiv.org/abs/2006.10460

Reliable contextual-bandit OPE depends on logged behavior probabilities and adequate support.
The paper develops high-confidence policy selection around self-normalized importance weighting.

Stage 5 therefore records the full behavior-policy propensity vector and evaluates candidate
ranking policies with both IPS and SNIPS.

The implementation does not claim to reproduce the paper's semi-empirical Efron-Stein bound.
It uses a paired nonparametric bootstrap around SNIPS differences and labels that distinction in
the output.

### Safety by Design: Realized-Cost Constraints for Contextual Bandits with Continuous Actions — arXiv:2608.26755

https://arxiv.org/abs/2608.26755

Recent safe-bandit work emphasizes that safety should account for realized cost rather than only
expected reward. Stage 5 stores a verified `realized_cost` with delayed outcomes and can block
promotion if observed direct candidate exposure exceeds a configured cost cap.

The repository-ranking action space here is discrete rather than the continuous action setting
studied in that paper, so the implementation adopts the safety principle rather than claiming a
direct algorithmic reproduction.

## Runtime modes

`context.learning.mode` supports:

### off

No learning record is written and runtime behavior is unchanged.

### observe

The baseline arm is always selected with propensity 1.0. Decision and retrieval-observation
records are written so the deployment can validate logging and outcome linkage before any
exploration occurs.

### explore

A bounded epsilon policy is used only when the classifier risk is `low`.

The safe online arm set is intentionally narrower than the Stage 3 benchmark profiles:

- `adaptive_math`;
- `source_rank`;
- `bm25_rank`;
- `rrf_only`;
- `rrf_mmr_050`;
- `rrf_mmr_075`;
- `rrf_mmr_090`.

The following Stage 3 interventions are deliberately excluded from online exploration:

- `selector_off`;
- `fixed_budget`;
- `no_early_stop`.

Those can change context ceilings or safety/escalation behavior and therefore remain offline
benchmark interventions.

## Propensity policy

For N eligible ranking arms and exploration probability epsilon:

```text
P(baseline) = 1 - epsilon + epsilon / N
P(other arm) = epsilon / N
```

Every active decision records:

- immutable decision ID;
- policy version;
- mode;
- baseline arm;
- eligible arms;
- chosen arm;
- chosen-arm propensity;
- full arm-propensity map;
- epsilon;
- whether the event was exploratory;
- safety reason;
- lane;
- risk;
- retrieval intent;
- SHA-256 task fingerprint;
- UTC decision timestamp.

Task text is not stored in the learning decision record.

## Fail-closed exploration

The behavior probability must be durably logged before an exploratory action is executed.

If decision logging fails:

```text
exploratory arm
      ↓
decision log failure
      ↓
discard exploratory action
      ↓
adaptive_math with propensity 1.0
```

If even the fallback record cannot be written, retrieval still proceeds with the deterministic
baseline and no OPE claim can be made for that event.

## Immutable record layout

Learning records live under:

```text
ai-workspace/generated/learning/
  decisions/<decision_id>.json
  observations/<decision_id>.json
  outcomes/<decision_id>.json
```

Records are created with exclusive-create semantics so an existing decision/outcome ID cannot
be overwritten by another process.

### Decision

Written before retrieval.

### Observation

Written after retrieval and linked by decision ID. It contains retrieval-side information that
is known immediately:

- elapsed retrieval milliseconds;
- selected context characters;
- fallback count;
- final sufficiency score;
- evidence state.

### Verified outcome

Written later by an explicit verifier or external workflow. It contains:

- success/failure;
- reward;
- realized cost;
- verification source;
- recorded timestamp;
- original decision timestamp;
- verification delay;
- optional metadata.

Stage 5 does not infer patch success from retrieval metrics.

## Emergency kill switch

Two independent controls exist:

1. `context.learning.kill_switch: true`;
2. environment variable `AI_WORKFLOW_LEARNING_KILL_SWITCH=1`.

Either forces the baseline.

The environment variable is intended as the fastest operational rollback because it does not
require editing the project config file.

## Off-policy evaluation

Use:

```bash
ai-workflow learning evaluate \
  --arm bm25_rank \
  --confidence 0.95 \
  --minimum-effective-sample-size 10 \
  --minimum-direct-exposures 5
```

For a deterministic target arm, Stage 5 evaluates the safe target policy:

```text
if target arm was eligible in the logged context:
    target policy chooses target arm
else:
    target policy chooses adaptive_math
```

This means high-risk and otherwise locked events remain baseline actions even during candidate
policy evaluation.

For each verified event:

```text
importance_weight =
    I(logged_action == target_action)
    / P_behavior(logged_action | context)
```

The report includes:

- IPS reward;
- SNIPS reward;
- IPS cost;
- SNIPS cost;
- matched event coverage;
- direct target-arm exposures;
- effective sample size;
- maximum importance weight;
- maximum direct observed realized cost.

## Confidence and promotion gate

Candidate and baseline SNIPS values are recomputed on bootstrap resamples of the same logged
events. The report estimates the candidate-minus-baseline reward and cost delta distributions.

A candidate is promotion-eligible only if all configured gates pass:

```text
effective sample size >= minimum ESS
AND direct target exposures >= minimum
AND reward delta lower confidence bound > safety margin
AND optional realized-cost cap is satisfied
```

Even when the gate passes:

```text
automatic_runtime_promotion = false
```

Stage 5 never writes the winning arm back into production configuration.

## Support and overlap

A low chosen-arm propensity creates a large importance weight. Large or highly variable weights
reduce effective sample size and make OPE unstable even when the raw event count is large.

This is why Stage 5 reports ESS and maximum importance weight rather than treating event count
alone as statistical support.

## Recommended rollout

### Phase 1 — observe

Run `mode: observe` first. Confirm decision/observation/outcome linkage and verification data
quality.

### Phase 2 — tiny low-risk exploration

Enable `mode: explore` with a small epsilon and only ranking arms that passed Stage 3/4 offline
analysis.

### Phase 3 — OPE

Collect enough verified outcomes and run IPS/SNIPS evaluation.

### Phase 4 — manual promotion review

Only consider a policy change after adequate overlap, ESS, confidence, and cost constraints.

## Not implemented intentionally

Stage 5 does not include:

- automatic policy promotion;
- high/medium-risk exploration;
- exploration over selector/sufficiency/context-budget controls;
- contextual model fitting;
- doubly robust OPE;
- theorem-equivalent confident-OPE bounds;
- unbounded epsilon adaptation.

Those require additional data and validation rather than more code.

## Stage 6 candidates

A future stage can add:

1. contextual feature schemas that are stable across releases;
2. doubly robust OPE with a separately validated reward model;
3. per-context candidate policies rather than global fixed-arm policies;
4. sequential confidence monitoring without repeated-testing inflation;
5. explicit promotion manifests with signed provenance and rollback metadata;
6. shadow evaluation before any newly promoted policy receives traffic.
