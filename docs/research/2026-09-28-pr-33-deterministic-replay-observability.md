# PR-33 — Deterministic replay and observability

Date: 2026-09-28

## Problem

AI Workflow already shared a run ID across retrieval diagnostics, local traces,
and provenance metadata. Traced runs also wrote an immutable local run journal
containing policy identity, workspace/graph fingerprints, bounded retrieval
diagnostics, and selected evidence descriptors.

The remaining gap was replayability. The journal was a snapshot, not an ordered
history, and it had no mechanism to detect event deletion, insertion,
reordering, or inconsistent edits. Documentation also referenced legacy
`ai-workflow run inspect/verify` commands that were not implemented.

PR-33 adds deterministic, read-only replay of recorded control-plane decisions.
It deliberately does **not** re-run models, providers, tools, MCP calls, network
requests, or other external effects.

## Research basis refreshed 2026-09-28

### Temporal deterministic replay

Temporal reconstructs workflow state by replaying event history. Previously
completed external operations return their recorded results during replay rather
than being executed again. Temporal also requires workflow decision logic to be
deterministic and places nondeterministic I/O outside the replay path.

https://docs.temporal.io/tasks
https://docs.temporal.io/workflow-definition

The relevant principle for AI Workflow is narrower than adopting Temporal:
reconstruct control-plane decisions from recorded history while external effects
remain outside replay.

### OpenTelemetry GenAI observability

Current OpenTelemetry GenAI conventions distinguish operations such as agent
invocation, workflow invocation, tool execution, and retrieval. The conventions
also warn that prompts, model messages, retrieval queries, tool arguments, and
tool results may contain sensitive information and should be opt-in rather than
blindly recorded.

https://opentelemetry.io/blog/2026/genai-observability/
https://opentelemetry.io/docs/specs/semconv/gen-ai/

PR-33 therefore records identities, hashes, policy decisions, safe locators, and
control-plane metadata rather than raw task/evidence content.

### OpenLineage run identity

OpenLineage models each execution as a distinct run with a unique run ID and
extensible run facets. AI Workflow already exposes an OpenLineage-shaped
provenance mapping and keeps one shared run ID across diagnostics.

https://openlineage.io/docs/spec/facets/run-facets/
https://openlineage.io/docs/spec/facets/

PR-33 retains that run identity instead of introducing a second incompatible
correlation ID.

## Design

### Versioned replay journal

Traced runs now emit:

`ai-workflow-run-journal-v2`

with `replay_mode=decision-history-only`.

The ordered event history is:

1. `routing`
2. `repository_routing`
3. `retrieval`
4. `ranking`
5. `selection`
6. `orchestration`
7. `authorization`

Each event contains:

- zero-based sequence number;
- stable event kind;
- previous event digest;
- structured safe payload;
- SHA-256 digest of the event body.

The journal stores the final event digest and event count, plus a SHA-256
digest over the complete journal record (excluding the digest field itself).
The ranking event records bounded text-free candidate descriptors so ranking
order can be reconstructed without persisting repository content.

### Integrity versus compatibility

These are intentionally separate checks.

**Integrity** asks whether the stored record is internally consistent:
schema/run identity, exact v2 event order, previous/event/head digests, event
count, duplicated retrieval/selection snapshots, and the complete-journal
digest. Integrity failure stops replay before compatibility checks and prevents
recorded events from being released.

**Compatibility** asks whether the current local state still matches the
recorded run:

- config digest;
- retrieval-policy/config version;
- workspace fingerprint;
- aggregate active-repository fingerprint;
- aggregate graph fingerprint.

A journal can be internally valid while the workspace has legitimately changed.

### Replay command

```bash
ai-workflow replay <run-id>
ai-workflow replay <run-id> --strict
```

Replay is read-only. It reads the local journal once, validates the complete
record, then checks current-state compatibility from that same verified snapshot.
Recorded events are returned only when integrity validation succeeds.

`--strict` exits nonzero when:

- the journal is missing;
- the event chain is invalid; or
- the current config/workspace/graph identity differs.

### Privacy boundary

The replay journal does not persist:

- raw task/query text;
- raw selected evidence text;
- prompts/completions;
- tool arguments/results;
- credentials or environment variables.

Selected evidence is represented by code-owned evidence IDs/content hashes,
source labels, and bounded locator/provenance fields.

## Important limitations

- The SHA-256 chain is integrity structure, not authentication. A malicious
  actor who can rewrite the entire journal can recompute the chain. Signed or
  externally anchored audit logs would be a separate feature.
- Replay reconstructs recorded control-plane history; it does not regenerate
  provider/model outputs or prove they would be identical today.
- Compatibility covers config, root-workspace, aggregate active-repository,
  and graph identity. It does not attempt to recreate the historical operating
  system, provider service, network state, or model backend.
- Journals are machine-local generated state and are written only when the
  existing telemetry/trace path is enabled.
- Timing data is historical observation and is not treated as a deterministic
  decision input.
- The `run_id` is a control-plane correlation identifier, not a W3C
  `traceparent` implementation.

## Acceptance criteria

- traced runs emit a v2 ordered replay history;
- event deletion/reordering/payload edits and top-level identity edits break
  integrity verification unless the complete journal is maliciously rewritten
  and all hashes are recomputed;
- raw task/evidence content is absent from the journal;
- `ai-workflow replay` performs no external execution;
- compatibility drift is reported separately from journal integrity;
- strict replay exits nonzero on missing/invalid/drifted state;
- legacy run-journal read/compatibility behavior remains available;
- full cross-platform CI/security/benchmark matrix passes before merge readiness.
