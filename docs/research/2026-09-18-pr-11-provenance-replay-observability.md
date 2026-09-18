# PR-11 — Provenance, Replay, and Observability Research

Date: 2026-09-18
Tracks: I-041 through I-044

## Main-branch baseline

PR-10 is merged into `main` at `2a19aaa961ecbbf6a61c8be3ad08984b879a3365`.
The merged SCIP implementation matches the PR-10 research plan, with one safer
refinement: language indexers write directly to central state via an explicit
output path instead of creating a repository-local `index.scip` and moving it.

## Existing provenance that PR-11 must reuse

The repository already has substantial provenance support:

- `RunMetadata` creates a unique UUID `run_id`.
- `RunMetadata.reproducibility_key()` hashes stable run inputs.
- `config_digest()`, `changed_files_digest()`, `index_manifest_digest()`,
  Git HEAD, provider versions, runtime identity, and immutable artifact
  references already exist.
- `LocalRunStore` persists immutable per-run provenance when explicitly
  requested.
- `WorkflowClient.prepare()` creates `RunMetadata` after retrieval.
- `RetrievalTrace` records retrieval timing/provider/sufficiency data, but it
  does not currently share the `RunMetadata.run_id`.
- `workspace_fingerprint()` is already returned in retrieval diagnostics.
- Code Review Graph already has a content hash and repository-bound freshness
  manifest, but there is no aggregate graph identity attached to runs.

PR-11 must bridge these pieces instead of creating a second provenance system.

## External evidence

### Execution provenance is more than final output

"From Agent Traces to Trust: Evidence Tracing and Execution Provenance in LLM
Agents" argues that agent auditability requires connecting retrieved evidence,
tool outputs, memory, observations, actions, and final outputs rather than
judging only final-answer accuracy:

https://arxiv.org/abs/2606.04990

"Reasoning Provenance for Autonomous AI Agents" similarly separates execution
traces/state checkpoints from structured provenance and proposes normalized,
queryable execution records for behavioral analysis and replay:

https://arxiv.org/abs/2603.21692

### Process traces are useful for reproducibility evaluation

AgentActionBench records agent behavior throughout experiment reproduction and
evaluates the resulting action traces rather than only final repositories:

https://arxiv.org/abs/2609.11117

### Interoperable trace identity

W3C Trace Context standardizes one trace identifier propagated across
distributed operations:

https://www.w3.org/TR/trace-context/

PR-11 keeps the existing UUID `run_id` as the control-plane execution
identity. It does not pretend that UUID is an OpenTelemetry/W3C `trace-id`
field because this package currently emits OTLP-compatible logs, not native
OpenTelemetry spans.

### GenAI observability

OpenTelemetry's 2026 GenAI observability guidance represents an agent execution
as an `invoke_agent` span with child model and tool spans, reinforcing the
need for one execution identity spanning retrieval/provider operations:

https://opentelemetry.io/blog/2026/genai-observability/

## Actual gaps

### I-041 — universal run identity

Today `WorkflowEngine` telemetry and `WorkflowClient` provenance create
separate records. Retrieval diagnostics have no `run_id`; `RunMetadata`
generates one only after retrieval.

Required behavior:

- create one run ID at the retrieval-engine boundary;
- expose it in retrieval diagnostics;
- include the same ID in `RetrievalTrace`;
- make `WorkflowClient` reuse that same ID in `RunMetadata`;
- callers that do not use `WorkflowClient` still receive the run ID through
  diagnostics.

### I-042 — policy/config identity

`RunMetadata` already stores a canonical config digest and schema version, but
retrieval diagnostics/traces do not expose them.

Required behavior:

- canonical `config_digest`;
- retrieval-policy/config schema version;
- effective algorithm policy used for the run;
- no raw secrets or task text in local provenance.

### I-043 — workspace + graph identity

Workspace fingerprinting already exists. CRG manifests already contain graph
SHA-256 and repository provenance.

Required behavior:

- retain existing workspace fingerprint;
- compute a stable, path-independent aggregate graph fingerprint from managed
  repository graph manifests/freshness state;
- include graph identity in diagnostics, trace, and `RunMetadata`;
- preserve compatibility when no graph exists.

### I-044 — replay/debug journal

Do not build a second tracing platform.

Use a small immutable local journal keyed by `run_id` that stores:

- run/policy/workspace/graph identities;
- retrieval intent/reason;
- providers attempted/skipped/errors;
- algorithm policy;
- sufficiency, selector, fallbacks, scheduler summary;
- selected evidence descriptors/provenance without raw evidence text.

A replay check verifies whether current config/workspace/graph identities still
match the recorded run. It does not silently re-run tools or providers.

This is deliberately a **replay-precondition/debug journal**, not a full
deterministic re-execution engine. Exact tool/model replay would require
capturing provider inputs/outputs and external model/tool determinism that the
current product does not guarantee.

## Privacy and security constraints

- Keep public API preparation side-effect-free by default.
- Do not store raw task text in the journal.
- Do not store raw selected evidence text.
- Journal writes are opt-in through the existing telemetry/write path.
- Use central generated state only.
- Journal files are immutable per run ID.
- No network authority is introduced.
- No new runtime dependency.
- No shell invocation.

## Scope

I-041 — one run ID across retrieval diagnostics, telemetry, and RunMetadata.
I-042 — policy/config identity recorded with each run.
I-043 — workspace + aggregate CRG graph fingerprint.
I-044 — immutable replay/debug journal with identity verification.
