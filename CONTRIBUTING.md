# Contributing

AI Workflow is a dependency-light Python 3.11+ control plane. Changes should preserve deterministic safety behavior, bounded resource use, cross-platform support, and compatibility unless a breaking change is explicitly justified.

## Development setup

The repository commits a universal `uv.lock`. Use the same pinned resolver version as CI (`uv 0.12.14`) and sync from the lock instead of resolving development tools independently:

```bash
uv sync --locked
uv lock --check
```

`uv sync` performs an exact sync by default. Do not use `--upgrade` in normal development or CI; dependency updates should be deliberate changes to `pyproject.toml` and `uv.lock`.

Run the full unit suite:

```bash
uv run --locked --no-sync python -m unittest discover -s tests -v
```

Run the same focused quality checks used by CI:

```bash
uv run --locked --no-sync python -m compileall -q ai_workflow
uv run --locked --no-sync ruff check ai_workflow tests security_tests scripts
uv run --locked --no-sync mypy ai_workflow
```

The mypy gate is intentionally an incremental typed-boundary gate. `--follow-imports=skip` keeps explicitly listed modules fully checked while preventing unrelated legacy implementation modules from becoming implicit targets merely because a public facade imports them. Add a module to the explicit list when its boundary is brought under the typed contract.

Before proposing changes to routing, retrieval, indexing, provider boundaries, persistence, releases, or verification, add or update a test that demonstrates the required behavior. Prefer the smallest change that satisfies the invariant.

## Hermetic package build

The build frontend and backend are also locked. To reproduce the package build used by CI:

```bash
uv sync --locked --only-group build
uv run --locked --no-sync python -m build --no-isolation
```

The `--no-isolation` flag is intentional here: build dependencies have already been installed exactly from `uv.lock`. Running a normal isolated build would resolve a second build environment independently.

## Pull requests

Keep changes focused and explain the behavior being changed, the risk boundary, and how it was verified. High-risk areas such as auth/security/payment guidance, provider execution, persistence, release automation, and concurrency require stronger review and explicit test evidence.

Do not weaken benchmark floors to make a regression pass. Update a baseline only when repeated measurements justify the new value and document the measurement source.

## Dependencies

The core package intentionally has no mandatory runtime dependencies. Prefer the standard library or an existing dependency. A new runtime dependency needs a concrete capability/security/maintenance justification and should remain optional when possible.

## Provider changes

Keep command execution shell-free, bounded, workspace-confined, and explicit about environment inheritance. New cache behavior must be opt-in and must not cache side-effecting or failed provider results.

## Release changes

Do not publish from feature branches. Release publishing is tag-triggered and should remain draft-until-complete. Never replace OIDC Trusted Publishing with a long-lived PyPI token unless the security model is intentionally redesigned and reviewed.
