# Retrieval evaluation stage 4 — 2026-09-11

Stage 4 adds statistical confidence, representative calibration, and conservative policy
selection on top of the Stage 3 causal retrieval experiments.

The central rule is unchanged: learned or statistically selected retrieval behavior remains
advisory. Deterministic high-risk routing is not delegated to a learned policy.

## Research basis

### Agent Retrieval Bench — arXiv:2607.24882

https://arxiv.org/abs/2607.24882

Agent Retrieval Bench demonstrates a calibration failure that is directly relevant here:
selective thresholds tuned on counterfactual wrong-repository controls do not improve success
on natural no-gold cases. Stage 4 therefore separates calibration and holdout data and reports
holdout performance instead of treating a tuned threshold as deployable evidence.

### Safe Exploration for Optimizing Contextual Bandits — arXiv:2002.00467

https://arxiv.org/abs/2002.00467

Safe Exploration starts from a production baseline and requires high-confidence evidence that
a candidate policy is at least as good before allowing safer exploration. Stage 4 adopts the
same conservative principle for retrieval-policy advice: the baseline remains selected unless
a candidate's lower confidence bound clears a configured safety margin.

### Confident Off-Policy Evaluation and Selection — arXiv:2006.10460

https://arxiv.org/abs/2006.10460

High-confidence off-policy evaluation requires logged action probabilities or otherwise valid
off-policy data. AI Workflow's current deterministic benchmark reports do not contain logging
propensities, so Stage 4 explicitly does not claim contextual-bandit OPE. The policy component
is an offline paired advisor only.

### Safety by Design — arXiv:2608.26755

https://arxiv.org/abs/2608.26755

Recent safe contextual-bandit work reinforces using explicit cost constraints rather than only
expected reward. AI Workflow keeps high and critical risk cases outside learned policy
selection entirely and retains deterministic safety rules.

## Paired bootstrap confidence

Use:

```bash
ai-workflow benchmark-statistics \
  --input seed-run.json \
  --confidence 0.95 \
  --resamples 5000 \
  --stratify task_type
```

The command consumes a Stage 3 seed-intervention run and pairs each retrieval/oracle condition
with its matching `random_non_gold` case.

For each downstream metric it reports:

- paired sample count;
- mean delta;
- percentile bootstrap confidence interval;
- wins, ties, and losses;
- paired win rate;
- Cohen's dz when variance is non-zero.

A confidence interval crossing zero is treated as inconclusive.

The bootstrap uses an explicit deterministic seed so analysis can be reproduced exactly.

## Stratification

`--stratify` may be repeated.

Examples:

```bash
--stratify task_type
--stratify repository_path
--stratify runner.metadata.language
```

Stratification does not manufacture statistical power. Small strata remain small and their
confidence intervals should be interpreted accordingly.

## Held-out cost-sensitive calibration

Use:

```bash
ai-workflow benchmark-calibrate \
  --input benchmark-report.json \
  --calibration-fraction 0.7 \
  --false-accept-cost 5 \
  --false-reject-cost 1
```

Eligible cases are:

- `positive`: evidence should be accepted;
- `natural_no_gold`: evidence should be rejected/abstained;
- `wrong_repo`: evidence should be rejected/abstained.

The split is deterministic and SHA-256 based, performed separately by label to reduce class
collapse. For every candidate threshold the calibration set reports:

- true positives / true negatives;
- false accepts / false rejects;
- true-positive and true-negative rates;
- false-accept and false-reject rates;
- balanced accuracy;
- total cost;
- expected cost per case.

Threshold selection minimizes:

```text
cost = false_accepts * false_accept_cost
     + false_rejects * false_reject_cost
```

Ties prefer fewer false accepts and then the more conservative threshold.

The selected threshold is then evaluated on the untouched holdout split.

The result is marked `advisory_only` and is never written to runtime configuration.

## Conservative retrieval-policy advisor

Use:

```bash
ai-workflow benchmark-policy-advisor \
  --input algorithm-report.json \
  --context-field task_type \
  --minimum-samples 10 \
  --confidence 0.95 \
  --safety-margin 0.0
```

The Stage 3 `adaptive_math` profile is the mandatory production baseline.

For positive cases, utility begins from file F1. For selective controls, utility begins from
whether abstention/control behavior was correct. Small configurable penalties are then applied
for context-budget utilization and latency.

Each candidate profile is paired against the same baseline cases. High and critical risk cases
are excluded before policy estimation.

For each context bucket and candidate arm, the advisor computes a bootstrap confidence interval
of paired utility deltas.

A profile becomes an advisory candidate only when:

```text
paired samples >= minimum_samples
AND lower confidence bound > safety_margin
```

Otherwise the baseline remains selected.

The output includes:

- per-context arm statistics;
- confidence bounds;
- eligible/ineligible state;
- recommended profile;
- explicit locked risk levels;
- `runtime_override_enabled: false`;
- `requires_randomized_logging_for_bandit_ope: true`.

## Why this is not yet a contextual bandit

The algorithm-ablation benchmark executes every profile offline on the same frozen cases. That
is excellent for paired causal comparison of the retrieval pipeline, but it is not logged
online bandit data.

Valid off-policy evaluation requires information about the behavior policy, normally including
the probability with which each action was chosen. Without those propensities, importance-
weighted contextual-bandit estimates would be misleading.

Stage 4 therefore stops before automatic online adaptation.

## Stage 5 prerequisites

A future online learning stage should begin only after the project has:

1. explicit action/arm IDs in production retrieval traces;
2. logging propensities for every eligible action;
3. a baseline action with deterministic safety fallback;
4. bounded exploration limited to low-risk contexts;
5. immutable outcome linkage between action, context, cost, and verified result;
6. delayed-outcome handling;
7. high-confidence off-policy evaluation before policy promotion;
8. rollback and kill-switch support;
9. enough representative data to avoid optimizing noise.

Until those prerequisites exist, statistical recommendations remain advisory.
