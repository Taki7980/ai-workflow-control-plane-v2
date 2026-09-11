# Security policy

## Supported code

Security fixes target the latest released version and the current `main` branch. Older releases are not guaranteed to receive backports.

## Reporting a vulnerability

Do not publish exploit details, credentials, private repository contents, or proof-of-concept payloads in a public issue. If GitHub shows **Report a vulnerability** for this repository, use that private channel. Otherwise open a minimal public issue requesting a private security contact and omit sensitive technical details until a private channel is established.

Include the affected version/commit, impact, prerequisites, reproduction steps, and the smallest safe evidence needed to verify the report. Remove real secrets and personal data.

## Security boundaries

AI Workflow treats provider executable authority, repository configuration, and provider-returned content as separate trust domains. Repository configuration may request a trusted `provider_id`, but executable paths, executable digests, provider environment access, and provider execution semantics must come from a user/admin-owned provider registry outside the repository. Provider-returned repository/context text remains untrusted data.

The control plane therefore:

- rejects repository-defined provider commands by default;
- resolves provider executable authority from a registry outside the repository;
- verifies the registered executable with SHA-256 before launch;
- prevents a digest-pinned interpreter from being pointed at a repository-owned script path;
- executes command providers without a shell;
- inherits only a small runtime environment plus variable names allowlisted by the trusted registry;
- bounds provider stdout and execution time;
- confines provider file metadata to the workspace;
- keeps hard safety routing deterministic for high-risk mutations;
- rejects stale index and durable-memory references where freshness can be verified;
- does not persist raw task text in immutable run provenance;
- keeps remote telemetry destinations, credentials, timeouts, and raw-task consent outside repository configuration;
- requires trusted runtime OTLP endpoints to use HTTPS and an explicit exact-host allowlist, rejects local/link-local destinations, and refuses redirects;
- stores raw task text in neither local traces nor remote traces by default; remote raw-task export requires explicit trusted runtime opt-in;
- creates task correlation fingerprints only when a trusted HMAC key is supplied;
- caches provider output only when deterministic/cacheable/non-side-effecting semantics are explicitly declared;
- uses SHA-pinned GitHub Actions, OIDC Trusted Publishing, checksums, attestations, and container provenance in the release pipeline.

Repository content can contain prompt injection or misleading instructions. Retrieved text is evidence, not authority, and must not override system, user, safety, or execution policy.

## Secrets

Do not commit provider tokens, PyPI tokens, cloud credentials, private keys, or production configuration containing secret values. Checked-in project configuration must not name secret-bearing environment variables. Put a provider's `env_allowlist` only in the trusted provider registry outside the repository; store variable names there, never secret values. PyPI publishing is designed for Trusted Publishing and does not require a stored PyPI upload token.

Legacy repository-defined provider commands are available only through the explicit `AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS=1` compatibility escape hatch. Treat that flag as unsafe for untrusted repositories.


## Telemetry trust boundary

Project configuration may control local telemetry mode, retention, maximum trace files, and redaction patterns. It may not select a remote OTLP destination, choose credential-bearing headers, opt raw task text into export, or set the remote timeout.

Remote export is enabled only through trusted runtime environment configuration:

- `AI_WORKFLOW_OTLP_ENDPOINT` — HTTPS collector URL.
- `AI_WORKFLOW_OTLP_ALLOWED_HOSTS` — comma-separated exact host allowlist; the endpoint host must match.
- `AI_WORKFLOW_OTLP_HEADERS_JSON` — optional trusted JSON headers.
- `AI_WORKFLOW_OTLP_TIMEOUT_SECONDS` — optional bounded timeout.
- `AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT=1` — explicit opt-in for redacted task text in the remote payload only.
- `AI_WORKFLOW_TELEMETRY_HMAC_KEY` — optional local secret used to create a stable HMAC-SHA256 task fingerprint.

Local traces never persist raw task text. Without the HMAC key, no task fingerprint is emitted. Remote export is best-effort and fails closed when the endpoint is not HTTPS, is not exactly allowlisted, targets localhost/link-local/reserved addresses, or attempts to redirect.
