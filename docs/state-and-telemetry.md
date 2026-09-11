# Durable state and telemetry

## Memory

AI Workflow stores durable memory in `ai-workspace/memory/memory.sqlite3` using SQLite transactions and WAL mode.

Runtime memory is local state, not repository content. The `ai-workspace/memory/` directory is ignored by Git except for its README and is excluded from Docker build context. A checked-in or copied `memory.jsonl` file is treated as untrusted data and is **never imported automatically** when the store starts.

Legacy JSONL import is an explicit trust decision. Review the source first, then call `SQLiteMemoryStore.import_jsonl(path)` from trusted operator tooling. Import is idempotent by record id.

Portable export remains available:

```bash
ai-workflow memory export --format jsonl --output memory-export.jsonl
```

The JSONL export is written atomically and can be used to migrate away from SQLite.

## Telemetry privacy

Retrieval traces are local JSON files under `ai-workspace/generated/traces`. Raw task text and unkeyed task fingerprints are not stored locally by default.

Project configuration may control local telemetry behavior such as mode, retention, trace-count limits, redaction patterns, and bounded export timeout. It does **not** have authority to choose an external telemetry destination, select credential-bearing headers, or enable raw task export.

Trusted runtime configuration controls external OTLP export through environment variables. The endpoint must use HTTPS, match an explicit allowlist, and pass destination safety checks. Redirects and local/link-local/private metadata-style destinations are rejected. Raw task export requires an explicit trusted runtime opt-in and redaction is applied before export.

A keyed telemetry fingerprint can be enabled with `AI_WORKFLOW_TELEMETRY_HMAC_KEY` when local correlation is needed without exposing a dictionary-guessable plain prompt hash.

Export failures remain best-effort and never make the local workflow fail. No OpenTelemetry SDK, MLflow, or other observability package is required at runtime.

## Retention and latency

`retention_days` prunes old trace files and `max_trace_files` caps the local trace count. `ai-workflow stats` reports budget/fallback aggregates and per-stage latency distributions with mean, p50, p95, and p99 values. Thresholds are observations only; this implementation does not invent a performance SLO.
