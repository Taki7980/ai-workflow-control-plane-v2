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
- aggregate Code Review Graph fingerprint;
- changed-file digest;
- canonical configuration digest;
- retrieval-policy/config schema version;
- index-manifest digest;
- configured provider versions;
- Python implementation/version/platform;
- optional model, dataset, or artifact references.

Raw task text is deliberately excluded from the immutable provenance record. `ArtifactReference` is only an interoperability vocabulary; recording a DVC-, MLflow-, registry-, or content-addressed URI does not add a dependency on that system. Security-sensitive artifact kinds (`model`, `dataset`, `policy`, `prompt-template`, `tool-schema`, and `safety-policy`) must also carry an immutable `sha256:<64-hex>` digest. Mutable URI/version-only references for those kinds are rejected when metadata is created or loaded.

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


## Unified run identity and deterministic replay

Retrieval diagnostics, local retrieval traces, and `RunMetadata` share one
control-plane `run_id`. The identifier correlates one preparation event; it is
not presented as a W3C `trace-id` or OpenTelemetry span identifier.

When retrieval telemetry is enabled, AI Workflow writes one immutable
`ai-workflow-run-journal-v2` record per run under:

```
ai-workspace/generated/run-journal/<run-id>.json
```

The journal contains policy/config identity, workspace and graph fingerprints,
configured provider versions, bounded retrieval diagnostics, selected evidence
identities, and an ordered SHA-256-linked control-plane event history:

```text
routing
 -> repository_routing
 -> retrieval
 -> ranking
 -> selection
 -> orchestration
 -> authorization
```

The ranking event records only bounded candidate descriptors such as rank,
source, content-derived dedupe key, score, and safe locator/provenance fields;
it does not store raw task text or raw `ContextItem.text`.

Replay a stored run without executing external effects:

```bash
ai-workflow replay <run-id>
```

Require both valid journal integrity and a matching current workspace:

```bash
ai-workflow replay <run-id> --strict
```

Replay separates two questions:

- **integrity** — do the fixed event order, per-event chain, duplicated snapshots,
  run identity, and complete-journal digest all agree?
- **compatibility** — do current config, root-workspace, aggregate repository,
  and graph identities still match the recorded run?

Integrity is checked before compatibility. If a v2 journal is invalid, replay
does not inspect journal-controlled compatibility inputs and does not return its
recorded events. The command never re-executes retrievers, tools, models,
providers, MCP calls, or network requests.

The hashes are not signatures: an attacker able to rewrite the entire local
journal can recompute them. They protect against accidental modification and
partial tampering, not a malicious writer with full file-rewrite capability.

The journal lives below `ai-workspace/generated/`, which remains ignored
machine-local state.

## Release reproducibility and publishing boundary

Release Python distributions use a measured reproducibility gate rather than
assuming that lockfiles imply deterministic output. CI and the release workflow
derive `SOURCE_DATE_EPOCH` from the exact source commit, create two independent
clean source trees with `git archive HEAD`, and build a wheel and sdist from
each using the locked toolchain. Wheels are compared directly. Each project
sdist is first normalized with a stdlib-only pax/gzip normalizer that fixes
archive timestamps, ownership fields, ordering and portable modes while
preserving file bytes and validating the sdist structure. The resulting release
artifacts must then have byte-identical names, sizes and SHA-256 digests.

The release emits `python-reproducibility.json` alongside the Python build
toolchain record. The first verified candidate becomes the published artifact;
there is no third unverified rebuild.

PyPI publishing is a separate trust boundary. The `pypi` environment job does
not checkout source or run build tools. It downloads only the wheel and sdist
from the draft GitHub release, verifies their GitHub artifact attestations
against the exact tag SHA/ref and release workflow, then invokes the official
PyPA Trusted Publishing action. PyPI's PEP 740 publish attestations are therefore
complementary to the repository's GitHub build attestations.

All external GitHub Actions used by repository workflows are required by tests
to remain pinned to full commit SHAs, and Dependabot tracks the
`github-actions` ecosystem so pin updates arrive as reviewable changes.

The reproducibility claim is deliberately narrow: wheel/sdist and the release
container are measured; platform-specific PyInstaller binaries are not claimed
to be reproducible. Attestations prove origin/integrity properties and do not
prove that released code is safe or correct.

