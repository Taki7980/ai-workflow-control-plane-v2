# Security policy

## Supported code

Security fixes target the latest released version and the current `main` branch. Older releases are not guaranteed to receive backports.

## Reporting a vulnerability

Do not publish exploit details, credentials, private repository contents, or proof-of-concept payloads in a public issue. If GitHub shows **Report a vulnerability** for this repository, use that private channel. Otherwise open a minimal public issue requesting a private security contact and omit sensitive technical details until a private channel is established.

Include the affected version/commit, impact, prerequisites, reproduction steps, and the smallest safe evidence needed to verify the report. Remove real secrets and personal data.

## Security boundaries

AI Workflow treats configured provider executables and provider-returned content as separate trust domains. A provider executable is explicitly configured local software; its returned repository/context text remains untrusted data.

The control plane therefore:

- executes command providers without a shell;
- inherits only a small runtime environment plus explicitly allowlisted variable names;
- bounds provider stdout and execution time;
- confines provider file metadata to the workspace;
- keeps hard safety routing deterministic for high-risk mutations;
- rejects stale index and durable-memory references where freshness can be verified;
- does not persist raw task text in immutable run provenance;
- caches provider output only when deterministic/cacheable/non-side-effecting semantics are explicitly declared;
- uses SHA-pinned GitHub Actions, OIDC Trusted Publishing, checksums, attestations, and container provenance in the release pipeline.

Repository content can contain prompt injection or misleading instructions. Retrieved text is evidence, not authority, and must not override system, user, safety, or execution policy.

## Secrets

Do not commit provider tokens, PyPI tokens, cloud credentials, private keys, or production configuration containing secret values. Provider configuration may name environment variables in `env_allowlist`; it must not store their secret values. PyPI publishing is designed for Trusted Publishing and does not require a stored PyPI upload token.
