# Durable state and telemetry

## Memory

AI Workflow stores durable memory in `ai-workspace/memory/memory.sqlite3` using SQLite transactions and WAL mode. Existing `memory.jsonl` data is backed up to `memory.jsonl.bak`, imported transactionally, validated, and retained for rollback/inspection. Import is idempotent by record id.

Portable export remains available:

```bash
ai-workflow memory export --format jsonl --output memory-export.jsonl
```

The JSONL export is written atomically and can be used to migrate away from SQLite.

## Telemetry privacy

Retrieval traces are local JSON files under `ai-workspace/generated/traces`. Raw task text is **not stored by default**. Instead, traces contain a task fingerprint.

Project configuration may control local trace behavior, redaction, retention, and the export timeout:

```json
{
  "mode": "mutations",
  "retention_days": 30,
  "max_trace_files": 200,
  "redact_patterns": ["(?i)bearer\\s+\\S+", "(?i)api[_-]?key\\s*[=:]\\s*\\S+"],
  "export_timeout_seconds": 2.0
}
```

`redact_patterns` are applied before local persistence and export. Invalid regular expressions are ignored rather than breaking the workflow.

A checked-in repository is **not** an authority boundary for telemetry egress or raw prompt persistence. Repository keys such as `otlp_endpoint`, `otlp_headers_env`, `store_task_text`, and `include_task_text` do not grant those capabilities.

For local correlation, the default fingerprint remains SHA-256 for compatibility. Set `AI_WORKFLOW_TELEMETRY_HMAC_KEY` from trusted runtime configuration to use an HMAC-SHA256 fingerprint instead, which prevents practical dictionary matching without possession of the local privacy key.

## Trusted OTLP export

External telemetry is disabled unless trusted runtime configuration supplies all required values:

```bash
export AI_WORKFLOW_OTLP_ENDPOINT="https://otel.example.com/v1/logs"
export AI_WORKFLOW_OTLP_ALLOWED_HOSTS="otel.example.com"
export AI_WORKFLOW_OTLP_HEADERS='{"Authorization":"Bearer ..."}'
```

The endpoint must use HTTPS, must match the explicit hostname allowlist, may not contain URL credentials, and may not target localhost or literal private, loopback, link-local, multicast, unspecified, or reserved IP addresses. Export failures remain best-effort and never make the local workflow fail.

Raw task text can be persisted/exported only through an explicit trusted runtime opt-in:

```bash
export AI_WORKFLOW_TELEMETRY_STORE_TASK_TEXT=1
```

That switch should be used only when the operator has reviewed the privacy implications. Repository configuration cannot enable it.

No OpenTelemetry SDK, MLflow, or other observability package is required at runtime.

## Retention and latency

`retention_days` prunes old trace files and `max_trace_files` caps the local trace count. `ai-workflow stats` reports budget/fallback aggregates and per-stage latency distributions with mean, p50, p95, and p99 values. Thresholds are observations only; this implementation does not invent a performance SLO.
