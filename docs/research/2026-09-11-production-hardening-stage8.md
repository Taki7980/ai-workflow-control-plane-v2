# Production rollout hardening — Stage 8

Date: 2026-09-11

Stage 8 does not widen learned-policy authority. It hardens Stage 7 around persistence,
operational recovery, correlated evidence, observability and incident response.

## Goals

Stage 8 adds:

- an opt-in same-host SQLite WAL evidence mirror;
- deterministic reconciliation against canonical immutable JSON evidence;
- stale local rollout-lock recovery after process crashes;
- cluster-aware bootstrap diagnostics for repeated task fingerprints;
- low-cardinality deployment metrics snapshots;
- signed, privacy-minimized rollback incident bundles.

It does not add a 100% learned-policy mode, automatic forward promotion or new risk classes.

## Canonical evidence and SQLite WAL

Stage 5 already writes immutable decision, observation and outcome JSON records before those
records can influence later policy evaluation.

Stage 8 preserves those files as the safety source of truth and adds a query-oriented mirror.

SQLite documents WAL as a mode where readers do not block a writer and a writer does not block
readers in the usual case. It also documents an important deployment constraint: WAL requires
all participating processes to be on the same host because its wal-index uses shared memory.

Reference:

https://sqlite.org/wal.html

Therefore Stage 8 makes the following claim only:

```text
one host / local filesystem
  canonical immutable JSON
        |
        +--> idempotent SQLite WAL mirror
        |
        +--> reconciliation
```

It does **not** use SQLite as:

- distributed consensus;
- a cross-host mutex;
- a network-filesystem coordination primitive.

The SQLite connection requires:

```text
journal_mode = WAL
synchronous = FULL
foreign_keys = ON
busy_timeout > 0
```

Every event stores:

- immutable event ID;
- event type;
- optional decision ID;
- optional policy ID and rollout generation;
- event timestamp;
- SHA-256 payload digest;
- canonical JSON payload.

Reinserting the exact same event ID and payload is idempotent. Reusing an event ID with a
different digest is rejected.

## Reconciliation model

Canonical files and SQLite are intentionally two representations of the same evidence.

`ai-workflow production reconcile` compares decision/observation/outcome IDs and SHA-256
payload digests.

The command reports:

- canonical events missing from SQLite;
- digest mismatches;
- extra SQLite events.

A mirror outage cannot authorize candidate behavior because candidate execution still depends on
the canonical pre-action decision record. The mirror can be backfilled later with
`ai-workflow production sync`.

## Local rollout lock recovery

Stage 7 used a directory lock around deployment-state transitions. Directory creation is useful
for a tiny local critical section, but a process crash can leave the directory behind.

Stage 8 adds:

- random ownership token;
- process ID;
- hashed host identifier;
- acquisition timestamp;
- stale threshold;
- owner-token check before release.

An existing lock younger than the threshold is never stolen. A lock older than the threshold
may be renamed out of the active path and removed before acquisition is retried.

The default threshold is 300 seconds. State transitions are expected to remain far shorter than
that window.

This is explicitly local crash recovery, not a distributed lease protocol.

## Correlated rollout evidence

Repeated requests derived from the same underlying task can be correlated. Treating them as
independent observations can make uncertainty look smaller than it is.

Cluster-bootstrap methods preserve within-cluster dependence by resampling whole clusters rather
than individual observations independently.

References:

https://pmc.ncbi.nlm.nih.gov/articles/PMC7148287/

https://s3alfisc.github.io/blog/post/2022-01-29-cluster-robust-inference-with-r/

Stage 8 groups live deployment evidence by `task_fingerprint` and resamples task clusters with
replacement.

The rollout report now contains:

```text
clustered_reward_difference
  rows
  clusters
  largest_cluster
  mean
  ci_low
  ci_high
```

This bootstrap is an additional robustness diagnostic. It does not replace Stage 7's sequential
guardrail and is not claimed to be a universal cluster-robust estimator for every workload.

Promotion requires a minimum number of clusters. A confidently negative cluster-bootstrap upper
bound beyond the configured regression margin is an independent rollback blocker.

## Observability contract

OpenTelemetry metric guidance recommends coherent namespaces, meaningful aggregation and
controlled attribute dimensions. High-cardinality request identifiers are generally poor metric
dimensions.

References:

https://opentelemetry.io/docs/specs/semconv/general/metrics/

https://opentelemetry.io/docs/languages/python/instrumentation/

Stage 8 provides a dependency-free JSON metrics snapshot with the namespace:

```text
ai_workflow.deployment.*
```

Only two attributes are exported:

```text
policy_id
stage
```

The export deliberately excludes:

- decision ID;
- task fingerprint;
- repository path;
- task text;
- repository content.

This is an interoperability contract, not an OTLP implementation. A later adapter can translate
it into a real OpenTelemetry SDK or external monitoring backend.

## Incident bundles

Rollback is a safety action. Incident capture must never be able to prevent it.

After automatic or manual rollback, Stage 8 attempts to create an immutable HMAC-SHA256-signed
incident bundle.

The bundle includes:

- incident ID;
- policy ID;
- rollout generation and stage;
- rollback reason;
- deployment-state SHA-256;
- guardrail-report SHA-256;
- latest signed state-history event;
- guardrail gate summary;
- aggregate deployment evidence;
- outcome-source counts;
- recent decision IDs for local lookup.

It explicitly excludes:

- raw task text;
- repository content;
- environment variables;
- signing-key material.

If incident generation or writing fails, the rollback remains successful.

## Separation of duties

NIST access-control guidance treats separation of duties as a real authorization property:
responsibilities are divided among distinct individuals or roles so one actor cannot complete a
sensitive action alone.

Reference:

https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final

Stage 8 does not simulate this with two arbitrary local strings. A legitimate multi-approver
Stage 9 design should bind approvals to independently authenticated principals or distinct
signing credentials and preserve those attestations in the deployment state.

## Commands

Enable the production mirror in configuration, then:

```bash
ai-workflow production sync
ai-workflow production status
ai-workflow production reconcile
```

Export deployment metrics:

```bash
ai-workflow deployment metrics --output deployment-metrics.json
```

Verify an incident bundle:

```bash
ai-workflow deployment verify-incident \
  --input ai-workspace/generated/learning/deployment/incidents/<id>.json
```

## Explicit non-goals

Stage 8 does not:

- make SQLite a networked or multi-host event store;
- provide distributed locking or consensus;
- implement native OTLP transport;
- make metrics cardinality unbounded;
- make incident capture rollback-critical;
- treat repeated task requests as independent clusters;
- invent multi-approver security without independent identities;
- widen candidate traffic above the Stage 7 25% bound;
- permit learned routing for medium/high-risk tasks.

## Stage 9 candidate

A future Stage 9 can introduce a real external coordination boundary:

- client/server durable event-store adapter;
- compare-and-swap deployment-state backend;
- independently authenticated promotion approvals;
- native OpenTelemetry/OTLP adapter;
- retention/compaction policies;
- incident export to external systems.

Those capabilities should be optional adapters. Local single-host operation should remain small
and dependency-light.
