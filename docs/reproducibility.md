# Library API, reproducibility, and cache semantics

AI Workflow separates a unique execution identity from deterministic content identity. A `run_id` identifies one preparation event and is intentionally random. `RunMetadata.reproducibility_key()` hashes the stable inputs that describe the environment and evidence state instead.

## Public library API

The package exports the same control-plane preparation path used by the CLI without duplicating routing or retrieval logic:

```python
import asyncio
from pathlib import Path

from ai_workflow import TaskRequest, WorkflowClient

result = asyncio.run(
    WorkflowClient().prepare(
        TaskRequest(
            text="Where is payment retry protection?",
            root=Path("."),
        )
    )
)

print(result.decision.lane.value)
print(result.retrieval["evidence_state"])
print(result.run.reproducibility_key())
```

Preparation is side-effect-free by default: the client disables retrieval telemetry writes and does not persist run files. To retain immutable provenance records explicitly opt in:

```python
client = WorkflowClient(persist_runs=True)
```

The default local store writes one JSON document per run under `ai-workspace/runs/`. A caller may inject another `RunStore` instead.

## Run provenance

`RunMetadata` records:

- control-plane version;
- workspace fingerprint and Git HEAD when available;
- changed-file digest;
- canonical configuration digest;
- retrieval-policy/config schema version;
- index-manifest digest;
- configured provider versions;
- Python implementation/version/platform;
- optional model, dataset, or artifact references.

Raw task text is deliberately excluded from the immutable provenance record. `ArtifactReference` is only an interoperability vocabulary; recording a DVC-, MLflow-, registry-, or content-addressed URI does not add a dependency on that system.

`to_openlineage()` produces an OpenLineage-shaped dictionary for integration code without importing or contacting an OpenLineage service.

## Provider identity and semantics

Command providers may declare a human-controlled version and execution semantics:

```json
{
  "name": "semantic",
  "command": ["python", "tools/semantic_provider.py"],
  "version": "2026.09",
  "semantics": {
    "deterministic": true,
    "cacheable": true,
    "idempotent": true,
    "side_effecting": false,
    "retryable": true
  }
}
```

Defaults are conservative: a provider with no declaration is not cache eligible. A result is cacheable only when the provider explicitly declares both `deterministic=true` and `cacheable=true`, declares no side effects, and the provider result itself is successful.

## Retrieval cache identity

`retrieval_cache_key()` hashes the retrieval-policy version, workspace fingerprint, provider name/version, query, intent, limits, changed-file list, and canonical request metadata. Absolute checkout paths are not part of the key, so equivalent workspaces can share deterministic identity without depending on where they were cloned.

`FileRetrievalCache` is an opt-in primitive. It is not automatically inserted into every retrieval call; callers choose where reuse is appropriate. Cache files use atomic replacement and malformed/failed cached results are ignored.

## Async interoperability

`AsyncRetriever` mirrors the synchronous `Retriever` result contract. `SyncRetrieverAdapter` can run a legacy synchronous retriever without changing its output semantics, while `CommandRetrieverAdapter` uses the native asyncio subprocess path. This provides a migration boundary without forcing the existing control-plane scheduler or every local filesystem operation to become async.
