# Retriever provider protocol and trust boundary

This document defines the command-provider boundary introduced by the research-backed provider hardening stage. It applies to the built-in semantic command and `context.external_retrievers`.

## Design goals

Provider executables are explicitly configured local programs, but their returned repository/context data is still treated as untrusted evidence. The control plane therefore separates executable trust from content trust, bounds resource use, confines file references to the workspace, and reports provider failures without silently turning every failure into an empty successful result.

The ranking/selection semantics are intentionally unchanged in this stage. The typed request/result boundary exists so later scheduling/concurrency work can reuse the same contract.

## Request

Providers receive one UTF-8 JSON object on stdin followed by a newline.

```json
{
  "query": "where is payment retry protection?",
  "root": "/absolute/workspace/root",
  "limit": 6,
  "intent": "semantic",
  "changed_files": [],
  "metadata": {}
}
```

`root` is diagnostic/provider context. Provider-returned `path` and `file` values do not gain permission to escape it.

## Response

A provider may return either:

1. one JSON object containing an `items` array;
2. one JSON array of item objects; or
3. JSONL, with one item object per non-empty line.

Example:

```json
{
  "items": [
    {
      "text": "PaymentService prevents duplicate retry charges with an idempotency key.",
      "score": 0.91,
      "path": "services/payment.py",
      "line": 88,
      "metadata": {"symbol": "charge"}
    }
  ]
}
```

Unknown item fields are ignored. Missing or malformed scores fall back to `0.0`. Empty text items are ignored.

## Path policy

Provider-supplied file references are untrusted. `path` and `file` metadata must be relative to the configured workspace root.

The control plane rejects:

- absolute paths;
- Windows drive-qualified paths;
- parent traversal (`..`);
- symlink-resolved paths that leave the workspace.

Rejected path metadata is removed while safe textual evidence remains usable. The item receives `path_rejected=true` and `rejected_path_fields` metadata so the loss of provenance is visible.

The same confinement rule is used for durable-memory source files and changed-file workspace fingerprints.

## Process limits

Every command provider is executed without a shell and receives:

- an explicit timeout;
- a hard stdout byte limit;
- stderr redirected away from context ingestion;
- a restricted environment instead of the full parent environment.

Default stdout limit: `8 MiB` (`8388608` bytes).

If a process exceeds the stdout limit it is terminated and the provider result is marked `output_limit`.

## Environment policy

A small platform/runtime environment is inherited so executables can start (`PATH`, Windows system variables, home/temp variables, locale, and Python UTF-8 variables).

Credentials and arbitrary process variables are **not inherited by default**. A provider that genuinely needs a variable must opt in by name:

```json
{
  "name": "private-docs",
  "command": ["python", "tools/private_docs_provider.py"],
  "intents": ["semantic"],
  "timeout_seconds": 8,
  "max_output_bytes": 2097152,
  "env_allowlist": ["PRIVATE_DOCS_TOKEN"]
}
```

Only the named variable is copied from the parent process. The configuration stores the variable name, not its secret value.

## Structured failures

Typed `ProviderResult` values distinguish evidence from failures. Current failure kinds are:

- `configuration` — invalid provider configuration;
- `launch` — executable/cwd could not be started;
- `timeout` — process exceeded its deadline;
- `output_limit` — stdout exceeded the configured byte limit;
- `exit` — provider returned a non-zero exit code;
- `empty_output` — successful process returned no payload;
- `invalid_payload` — output did not satisfy JSON/JSONL protocol;
- `not_configured` — semantic provider is disabled/unconfigured.

The adaptive broker exposes attempted-provider failures under `diagnostics.provider_errors` and still falls back to safe base retrieval when possible.

## Typed Python boundary

`ai_workflow.retrieval_contracts` defines:

- immutable `RetrievalRequest`;
- immutable `ProviderResult`;
- `Retriever` protocol.

`ai_workflow.provider_runner` defines normalized `CommandProviderSpec` plus the shared bounded command runner.

The existing `semantic_context(...)` and `run_retriever(...)` list-returning APIs remain available for compatibility. New orchestration code should prefer the typed result APIs when it needs failure information.

## Semantic provider configuration

```json
{
  "context": {
    "semantic": {
      "mode": "auto",
      "command": ["python", "tools/semantic_provider.py"],
      "timeout_seconds": 8,
      "max_results": 6,
      "max_output_bytes": 8388608,
      "env_allowlist": []
    }
  }
}
```

String commands remain supported for compatibility. An argv array is preferred where quoting/paths may differ across operating systems.

## External retriever configuration

```json
{
  "context": {
    "external_retrievers": [
      {
        "name": "docs",
        "command": ["python", "tools/docs_provider.py"],
        "intents": ["semantic", "mixed"],
        "timeout_seconds": 5,
        "max_output_bytes": 4194304,
        "env_allowlist": []
      }
    ]
  }
}
```

Valid intents remain `exact`, `semantic`, `structural`, `mixed`, and `all`.

## Compatibility and migration

Existing configurations that only specify `command`, `intents`, and `timeout_seconds` continue to work. Missing `max_output_bytes` defaults to 8 MiB and missing `env_allowlist` defaults to an empty list.

One intentional behavior change is that provider processes no longer inherit arbitrary environment variables. If a provider relied on implicit credential inheritance, add only the required variable names to `env_allowlist`.
