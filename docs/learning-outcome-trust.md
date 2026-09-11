# Learning outcome trust boundary

Adaptive retrieval may learn only from outcomes that carry attributable, immutable verification evidence.

`record_verified_outcome()` requires:

- a trusted verifier source ID;
- a non-empty verifier identity;
- an immutable `sha256:<64 hex>` evidence digest;
- reward in the closed interval `[0.0, 1.0]`;
- non-negative finite realized cost.

The built-in verifier source IDs are deliberately small and code-owned. Operators may extend them through the trusted runtime environment variable `AI_WORKFLOW_TRUSTED_OUTCOME_SOURCES`. Repository configuration is not consulted when deciding who can assert a verified outcome.

Example:

```python
record_verified_outcome(
    root,
    decision_id,
    success=True,
    source="github-actions:test-suite",
    verifier_identity="repo/workflow/run-id/check-id",
    evidence_digest="sha256:<digest of immutable verification evidence>",
    reward=1.0,
    realized_cost=0.12,
)
```

The evidence digest should identify a stable artifact such as a test result bundle, attestation, signed review record, or other independently retained verification output. A caller-provided `verified=True` flag is not accepted as evidence.

This layer validates identity shape and immutable evidence references. Higher-assurance deployments should additionally verify the referenced CI/OIDC attestation or digital signature before admitting the outcome into learning data.
