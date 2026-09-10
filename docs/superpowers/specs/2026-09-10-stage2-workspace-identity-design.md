# Stage 2 Multi-Repo Control and Workspace Identity

## Goal
Harden the multi-repo registry from PR #18 and add explicit repository management plus deterministic per-repository and aggregate workspace identity.

## Scope
- Never persist raw Git remote credentials or raw remote URLs.
- Fail closed on malformed/unsupported registries.
- Confine registry-controlled repository paths to the workspace root, including symlink escape prevention.
- Add `ai-workflow repos list|refresh|include|exclude` with JSON-capable deterministic output.
- Preserve explicit include/exclude decisions across refresh when repository identity is unchanged; reset inclusion when a path's remote identity changes.
- Add stable repository IDs and per-repository Git/worktree fingerprints.
- Add an aggregate workspace fingerprint independent of absolute checkout path.

## Non-goals
- Learned/LLM repository routing.
- Global multi-repo context-budget allocation.
- Cross-repository dependency graph construction.
- Per-repository retrieval ranking changes.
- Local daemon/background service.

## Registry contract
Persist only: `name`, `relative_path`, `git_dir`, `remote_identity`, `head_ref`, `head_sha`, `included`, `reason`, and deterministic `repository_id`. Raw remote URLs are read transiently only to derive `remote_identity`.

Registry version mismatches, invalid JSON, invalid top-level shapes, duplicate entries, unsafe paths, and missing/non-Git directories must not activate repository roots.

## Repository management
`repos refresh` performs read-only discovery, merges by `(relative_path, remote_identity)`, preserves prior inclusion only for unchanged identity, marks newly discovered repositories excluded, and atomically rewrites the registry.

`repos include` and `repos exclude` accept an exact relative path, exact repository ID, exact remote identity, or unique name. Ambiguous or missing selectors fail without writes.

## Workspace identity
A repository snapshot contains repository ID, workspace-relative path, remote identity, Git HEAD/ref, dirty-state digest, optional index-state digest, and a stable fingerprint. The aggregate fingerprint hashes only stable repository snapshots in deterministic relative-path order, never absolute checkout paths.

## Compatibility and safety
- Python 3.10+.
- No new runtime dependency.
- Existing `workspace.roots` compatibility remains unchanged.
- Existing single-root `workspace_fingerprint()` API remains available.
- Registry paths use the existing `resolve_within_root()` policy.
- Writes use existing atomic JSON utilities.

## Verification
Add adversarial tests for credential-bearing remotes, path traversal, absolute paths, symlink escape, malformed registries, refresh decision preservation/reset, selector ambiguity, deterministic ordering, repository-state changes, and checkout-path-independent aggregate fingerprints. Full CI must pass on the repository's Python/platform matrix.