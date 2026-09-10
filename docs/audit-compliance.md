# Technical audit compliance matrix

This matrix records the implementation status of the research-backed Technical Audit and Improvement Plan as of 2026-09-10. It distinguishes implemented repository controls from external release activation and from recommendations that were explicitly conditional on profiling evidence.

Status meanings: **Complete** means the behavior is implemented and covered by repository verification. **External activation** means the repository path exists but a third-party account or review must still be configured. **Conditional** means the audit itself required evidence before implementation, so adding the feature without that evidence would be contrary to the plan.

| Priority | Audit recommendation | Status | Evidence |
| --- | --- | --- | --- |
| P0 | Typed retrieval request/result boundary and stable provider protocol | Complete | PR #9; `ai_workflow/retrieval_contracts.py`, `docs/provider-protocol.md` |
| P0 | Provider trust boundary: no shell, restricted environment, output/time limits, structured failures, workspace path confinement | Complete | PR #9; `ai_workflow/provider_runner.py`, `ai_workflow/path_policy.py` |
| P0 | Bounded concurrent retrieval with one global deadline, deterministic aggregation, and sibling failure isolation | Complete | PR #10; `ai_workflow/workflow_engine.py`, `ai_workflow/retrieval_scheduler.py`, `docs/concurrency.md` |
| P0 | Preserve deterministic high-risk routing and explicit evidence abstention/exploration behavior | Complete | Existing classifier/retrieval-policy contracts plus regression suite |
| P0 | Safe setup, atomic generated-state writes, bounded selector work, typed orchestration output, stable doctor contract | Complete | PR #14; `docs/core-contracts-and-setup.md` |
| P1 | Incremental index fast path using size/mtime with strict content-hash verification mode | Complete | PR #11; `ai_workflow/indexer.py`, `docs/incremental-indexing.md` |
| P1 | Versioned typed configuration with migration, unknown-field preservation, and future-version refusal | Complete | PR #12; `ai_workflow/typed_config.py`, `docs/configuration-migrations.md` |
| P1 | Transactional durable memory, legacy migration/export, privacy-aware telemetry, retention, and tail-latency metrics | Complete | PR #13; `ai_workflow/memory_store.py`, `ai_workflow/telemetry.py`, `docs/state-and-telemetry.md` |
| P1 | Python 3.10-3.14/Linux plus Windows/macOS compatibility, focused lint/type checks, package smoke tests | Complete | PR #15; `.github/workflows/tests.yml` |
| P1 | Measured benchmark regression policy with overall and per-query-type floors | Complete | PR #15; `benchmarks/baseline.json`, `ai_workflow/benchmark_regression.py` |
| P1 | Single package-version source and current package metadata | Complete | PR #15; `ai_workflow/_version.py`, `pyproject.toml` |
| P1 | Public library API that reuses the application engine rather than the CLI | Complete | Final audit PR; `ai_workflow/api.py`, package exports |
| P1 | Reproducible run identity/provenance including workspace, config, index, provider, runtime, and external-artifact references | Complete | Final audit PR; `ai_workflow/provenance.py`, `docs/reproducibility.md` |
| P1 | Explicit deterministic/cacheable provider semantics and path-independent retrieval cache identity | Complete | Final audit PR; `ai_workflow/execution_semantics.py`, `ai_workflow/retrieval_cache.py` |
| P1 | Async provider migration boundary without forcing all filesystem work async | Complete | Final audit PR; `AsyncRetriever`, retriever adapters, native async command runner |
| P1 | Close subprocess resource leak reported by expanded CI | Complete | Final audit PR; sync provider runner closes stdin/stdout after reader shutdown |
| P2 | PyPI Trusted Publishing using GitHub OIDC rather than a stored upload token | External activation | PR #16 release workflow is carried into the final main-targeting PR; repository workflow is complete, but the PyPI Trusted Publisher and `pypi` environment must be configured before the first release tag |
| P2 | Native Linux/Windows/macOS binaries, SHA-256 checksums, and GitHub artifact attestations | Complete | PR #16 release assets carried into the final main-targeting PR; `.github/workflows/release.yml` |
| P2 | Non-root container distribution with provenance/SBOM | Complete | PR #16 release assets carried into the final main-targeting PR; `Dockerfile`, release workflow |
| P2 | Checksum-verifying POSIX/PowerShell installers and WinGet/Homebrew/Conda manifest foundations | Complete | PR #16 release assets carried into the final main-targeting PR; `install.sh`, `install.ps1`, `packaging/` |
| P2 | Actual WinGet/Homebrew index acceptance | External activation | Repository manifests/rendering are complete; upstream package repositories require their own submission/review process |
| P2 | Security, contribution, release/reproducibility documentation | Complete | `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/reproducibility.md` |
| P3 | Long-running local daemon/service for index/cache reuse | Conditional | Not implemented. The audit made this conditional on profiling showing material startup/re-index overhead. Current design retains the lightweight modular monolith until measurements justify a daemon. |

## Why PR #16 appears again here

PR #16 was reviewed and merged, but its base branch was `feat/audit-ci-supply-chain`, not `main`. After PR #15 was merged to `main`, merging #16 therefore advanced that feature branch rather than the default branch. The final audit PR intentionally carries the already-reviewed #16 release/distribution tree to `main` together with the remaining audit closure so the default branch reaches the intended state.

## Verification rule

A row is not considered complete because a file merely exists. Behavior-changing rows must have tests or CI evidence, and the final PR must pass the repository's Linux/Windows/macOS compatibility matrix, focused Ruff/mypy checks, package installation smoke tests, `doctor --strict`, and measured benchmark regression gate before merge.
