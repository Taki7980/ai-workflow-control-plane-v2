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
- a bounded stderr diagnostic tail;
- a restricted environment instead of the full parent environment.

Default stdout limit: `8 MiB` (`8388608` bytes).
Default stderr diagnostic limit: `64 KiB` (`65536` bytes).

If stdout exceeds its limit, the provider process tree is terminated and the result is marked `output_limit`. stderr is drained independently so a noisy provider cannot block on a full pipe; only the configured tail is retained. stderr never becomes retrieval evidence.

## Trusted provider registry

Repository configuration no longer grants executable authority by default. A project selects a provider by opaque `provider_id`:

```json
{
  "context": {
    "semantic": {
      "mode": "auto",
      "provider_id": "semantic-local",
      "timeout_seconds": 8,
      "max_results": 6,
      "max_output_bytes": 8388608
    },
    "external_retrievers": [
      {
        "name": "private-docs",
        "provider_id": "private-docs-v1",
        "intents": ["semantic", "mixed"],
        "timeout_seconds": 5,
        "max_output_bytes": 4194304
      }
    ]
  }
}
```

Executable authority lives in a separate user/admin-owned JSON file outside the repository. Set its absolute path with `AI_WORKFLOW_PROVIDER_REGISTRY`; otherwise the platform user configuration directory is used.

```json
{
  "providers": {
    "semantic-local": {
      "command": ["/opt/ai-workflow/providers/semantic-provider"],
      "sha256": "<64-lowercase-hex-digest>",
      "timeout_seconds": 8,
      "max_output_bytes": 8388608,
      "env_allowlist": ["SEMANTIC_PROVIDER_TOKEN"],
      "semantics": {
        "deterministic": true,
        "cacheable": true,
        "side_effect_free": true
      }
    }
  }
}
```

The registry must be outside the repository. Its executable must be an absolute, non-symlink regular-file path outside the repository and its SHA-256 digest must match during registry resolution. That digest is carried in the immutable provider spec and reverified immediately before both synchronous and asynchronous process launch. A changed, replaced, symlinked, or repository-moved executable fails closed with `provider_trust`.

Repository configuration can tighten timeout/output limits and choose intents, but it cannot provide or override the executable, digest, environment allowlist, neutral-CWD policy, stderr cap, version identity, or execution semantics. This prevents a malicious repository from converting data/configuration authority into local-code or credential authority.

A digest-pinned interpreter is also prevented from being pointed at an existing repository-owned script path. If a trusted provider needs a helper script, register it with an absolute path outside the project and treat that helper as part of the trusted provider installation.

## Working-directory isolation

Trusted registry providers default to an ephemeral neutral working directory that exists only for the lifetime of the provider process. The repository path is still supplied explicitly in the JSON request as `root`; it is not granted as ambient process state through the current working directory.

A trusted user/admin registry may set `neutral_cwd=false` for a compatibility provider that genuinely requires the historical executable-directory CWD. Checked-in repository configuration cannot weaken this policy. Unsafe legacy repository-defined commands retain their historical repository CWD only behind `AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS=1`.

## stderr diagnostics

Provider stderr is diagnostic data only. The runner:

- drains stderr concurrently with stdout;
- retains only the configured tail;
- marks `stderr_truncated=true` when earlier data was discarded;
- redacts literal values of environment variables explicitly passed through the trusted `env_allowlist`;
- redacts common bearer, authorization, API-key, token, password and secret assignments;
- exposes the result as `ProviderResult.stderr_tail` and `stderr_truncated`.

stderr is never converted into `ContextItem` evidence.

## Environment policy

A small platform/runtime environment is inherited so executables can start (`PATH`, Windows system variables, home/temp variables, locale, and Python UTF-8 variables).

Credentials and arbitrary process variables are **not inherited by default**. Environment variables required by a provider must be named only in the trusted provider registry's `env_allowlist`. Checked-in project configuration cannot expand this list.

## Unsafe legacy compatibility

Direct `command` fields remain parseable for migration, but runtime execution is disabled by default. `AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS=1` explicitly restores the old behavior for trusted legacy repositories. Do not enable that flag when opening or operating on an untrusted repository.

## Structured failures

Typed `ProviderResult` values distinguish evidence from failures. Current failure kinds are:

- `configuration` — invalid provider configuration;
- `provider_trust` — trusted executable identity or path policy changed before launch;
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

## Configuration examples

Use `provider_id` in repository configuration and keep executable authority in the trusted provider registry described above.

## Compatibility and migration

Migrate every repository-defined semantic/external provider `command` to a trusted registry entry. Replace the checked-in `command`, `env_allowlist`, and execution semantics with only `provider_id` plus non-authority controls such as intents and tighter timeout/output limits.

The legacy command path is intentionally fail-closed unless `AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS=1` is set.

