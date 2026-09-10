# Reproducibility, run identity, and external artifact references

AI Workflow separates random execution identity from deterministic workspace/content identity. `run_id` is a UUID unique to one execution and is never used as a content cache key.

`RunMetadata` records schema version, control-plane version, workspace fingerprint, Git HEAD when available, changed-file digest, config digest, retrieval-policy version, index-manifest digest, provider versions, Python/platform runtime information, and optional external artifact references. Raw task text is deliberately excluded from immutable run metadata.

`ArtifactReference` is an interoperability vocabulary, not a dependency. MLflow-style model URIs, DVC-style dataset revisions, or another content-addressed URI may be recorded with optional digest/version/role fields. `to_openlineage()` maps the local record to run/job/input/output concepts as an ordinary dictionary without importing or contacting OpenLineage.

Retrieval cache keys include retrieval-policy version, deterministic workspace fingerprint, provider name/version, and canonical request parameters. Absolute checkout paths are excluded. Provider output may be cached only when the provider explicitly declares `deterministic=true`, `cacheable=true`, and `side_effecting=false`.

`LocalRunStore` writes one immutable JSON document per run under `ai-workspace/runs/` by default through the public `WorkflowClient.prepare()` API. Callers may inject another `RunStore` or disable persistence.
