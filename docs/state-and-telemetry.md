# Durable state and telemetry

## Memory

AI Workflow stores durable memory in `ai-workspace/memory/memory.sqlite3` using SQLite transactions and WAL mode. Existing `memory.jsonl` data is backed up to `memory.jsonl.bak`, imported transactionally, validated, and retained for rollback/inspection. Import is idempotent by record id.

Portable export remains available:

```bash
ai-workflow memory export --format jsonl --output memory-export.jsonl
```

The JSONL export is written atomically and can be used to migrate away from SQLite.

## Telemetry privacy

Retrieval traces are local JSON files under `ai-workspace/generated/traces`. Raw task text is **not stored by default**. Instead, traces contain a SHA-256 task fingerprint.

Optional configuration keys under `context.telemetry`:

```json
{
  "mode": "mutations",
  "store_task_text": false,
  "retention_days": 30,
  "max_trace_files": 200,
  "redact_patterns": ["(?i)bearer\\s+\\S+", "(?i)api[_-]?key\\s*[=:]\\s*\\S+"],
  "otlp_endpoint": "",
  "export_timeout_seconds": 2.0,
  "otlp_headers_env": ""
}
```

`redact_patterns` are applied before local persistence and export. Invalid regular expressions are ignored rather than breaking the workflow. If task storage is enabled, sensitive substrings can therefore still be removed before persistence.

## Optional OTLP export

When `otlp_endpoint` is set, the zero-dependency core sends a best-effort OTLP-compatible JSON/HTTP log envelope. Export failures never make the local workflow fail. Authentication headers can be supplied indirectly by naming an environment variable in `otlp_headers_env`; that variable should contain a JSON object of HTTP headers.

No OpenTelemetry SDK, MLflow, or other observability package is required at runtime.

## Retention and latency

`retention_days` prunes old trace files and `max_trace_files` caps the local trace count. `ai-workflow stats` reports budget/fallback aggregates and per-stage latency distributions with mean, p50, p95, and p99 values. Thresholds are observations only; this implementation does not invent a performance SLO.
