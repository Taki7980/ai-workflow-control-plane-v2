# Contributing

AI Workflow is a dependency-light Python 3.10+ control plane. Changes should preserve deterministic safety behavior, bounded resource use, cross-platform support, and compatibility unless a breaking change is explicitly justified.

## Development setup

Clone the repository, create a virtual environment, then install the development extras:

```bash
python -m pip install -e ".[dev]"
```

Run the full unit suite:

```bash
python -m unittest discover -s tests -v
```

Run the same focused quality checks used by CI:

```bash
python -m compileall -q ai_workflow
ruff check --select E,F,UP,BLE,EXE ai_workflow scripts
mypy --follow-imports=skip ai_workflow/retrieval_contracts.py ai_workflow/path_policy.py ai_workflow/typed_config.py ai_workflow/benchmark_regression.py ai_workflow/execution_semantics.py ai_workflow/provenance.py ai_workflow/retrieval_cache.py ai_workflow/retrieval_adapters.py ai_workflow/api.py ai_workflow/provider_runner.py
```

The mypy gate is intentionally an incremental typed-boundary gate. `--follow-imports=skip` keeps explicitly listed modules fully checked while preventing unrelated legacy implementation modules from becoming implicit targets merely because a public facade imports them. Add a module to the explicit list when its boundary is brought under the typed contract.

Before proposing changes to routing, retrieval, indexing, provider boundaries, persistence, releases, or verification, add or update a test that demonstrates the required behavior. Prefer the smallest change that satisfies the invariant.

## Pull requests

Keep changes focused and explain the behavior being changed, the risk boundary, and how it was verified. High-risk areas such as auth/security/payment guidance, provider execution, persistence, release automation, and concurrency require stronger review and explicit test evidence.

Do not weaken benchmark floors to make a regression pass. Update a baseline only when repeated measurements justify the new value and document the measurement source.

## Dependencies

The core package intentionally has no mandatory runtime dependencies. Prefer the standard library or an existing dependency. A new runtime dependency needs a concrete capability/security/maintenance justification and should remain optional when possible.

## Provider changes

Keep command execution shell-free, bounded, workspace-confined, and explicit about environment inheritance. New cache behavior must be opt-in and must not cache side-effecting or failed provider results.

## Release changes

Do not publish from feature branches. Release publishing is tag-triggered and should remain draft-until-complete. Never replace OIDC Trusted Publishing with a long-lived PyPI token unless the security model is intentionally redesigned and reviewed.
