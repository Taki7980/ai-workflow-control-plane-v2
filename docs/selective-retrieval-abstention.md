# Selective retrieval and abstention calibration

PR-26 adds a deterministic evidence-quality gate after retrieval and context
selection. It is intentionally separate from model confidence and provider
scores.

## Why

Agent Retrieval Bench (2026) reports that simple score thresholds calibrated
on counterfactual wrong-repository controls do not transfer reliably to natural
no-gold cases. Evidence-sufficiency work also shows that irrelevant, absent,
and conflicting evidence require different abstention behavior. The control
plane therefore does not treat one retriever score as a universal probability.

## Conditions

The gate records one of:

- `supported`: existing sufficiency contract passes and deterministic quality
  checks pass.
- `partial`: useful evidence exists but the sufficiency/structural contract is
  incomplete.
- `irrelevant`: evidence is stale-only or query coverage is below the trusted
  floor.
- `no_context`: no evidence survived selection.
- `conflicting`: code-owned structural evidence proves both verified-empty and
  present results for the same relation/symbol.
- `wrong_repository`: evidence identity falls outside PR-24's authorized
  repository routing plan.

For ANSWER lanes, rejected evidence produces `abstain`. For SMALL/FULL lanes,
it produces `requires_exploration`. The gate never grants tool, policy,
repository, or execution authority.

## Calibration

Trusted project config may set:

```json
{
  "context": {
    "selective_retrieval": {
      "enabled": true,
      "minimum_coverage": 0.15
    }
  }
}
```

The coverage floor is a bounded deterministic feature, not a calibrated
probability. Disabling the gate preserves the pre-PR-26 evidence-state behavior
for compatibility, while diagnostics still report what the gate would have
decided.

## Auditability

Diagnostics and run journals record the condition, acceptance decision, score,
reasons, and whether enforcement was enabled. This supports later benchmark
calibration without silently changing production behavior.
