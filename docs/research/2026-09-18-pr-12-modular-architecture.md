# PR-12 — Modular Architecture Research

Date: 2026-09-18
Tracks: I-045 through I-048

## Baseline verified on main

PR-11 is merged into `main` at `ed31f242c7cc475c60151415b57e9e4cf1c2f4bc`.

Current hotspots:
- `ai_workflow/cli.py`: 1,613 lines / 49 command handlers.
- `ai_workflow/workflow_engine.py`: 935 lines.
- `ai_workflow/context_broker.py`: 829 lines.
- `ai_workflow/deployment_state.py`: 665 lines.
- `ai_workflow/repository_registry.py`: 669 lines.
- `ai_workflow/retrieval_learning.py`: 610 lines.

The console entry point is already stable at:
`ai-workflow = ai_workflow.entrypoint:main`.

The package-level public API is intentionally small:
`TaskRequest`, `WorkflowClient`, `WorkflowResult`, `prepare`, `__version__`.

## External guidance

### Preserve public behavior while refactoring internals

Python PEP 387 treats public module/function names, argument behavior, return values,
side effects, and commonly raised exceptions as backwards-compatibility commitments:
https://peps.python.org/pep-0387/

PR-12 therefore treats the refactor as behavior-preserving. Existing import paths and
CLI command semantics stay valid.

### Split multifunction CLIs by subcommand/domain

The Python `argparse` documentation explicitly recommends subcommands when one
program performs multiple different functions:
https://docs.python.org/3/library/argparse.html

The current monolithic parser already has natural domain groups:
- workspace/project/repository commands
- memory
- benchmark/evaluation
- learning
- deployment
- production

### Repository structure matters for agentic software engineering

SWE-Adept reports improved repository-level localization from selective dependency
traversal and minimizing irrelevant context:
https://arxiv.org/abs/2603.01327

Codified Context reports domain-specialized context structures for large codebases:
https://arxiv.org/abs/2602.20478

Reproducibility in the Age of Agentic AI argues that repository structure, tests,
commit history, instructions, and decision records are part of the durable context
that coding agents depend on:
https://arxiv.org/abs/2609.11728

These support narrower domain modules and explicit package boundaries rather than a
single command module importing the entire product.

## Design decision

This final roadmap PR is a **behavior-preserving modularization**, not a rewrite.

### 1. CLI command modules

Create `ai_workflow/commands/`:
- `common.py`: root/JSON/input helpers only.
- `workspace.py`: setup/bootstrap/init/route/repos/brief/context/index/doctor/handoff/compress/verify/stats.
- `memory.py`: memory commands.
- `evaluation.py`: benchmark corpus + benchmark/evaluation commands.
- `learning.py`: learning commands.
- `deployment.py`: staged deployment commands.
- `production.py`: production-store commands.
- `parser.py`: parser construction and command registration.

`ai_workflow/cli.py` becomes a compatibility facade exposing the same handler names,
`build_parser()`, and `main()`.

### 2. Explicit internal package boundaries

Create domain packages:
- `ai_workflow/retrieval/`
- `ai_workflow/provider/`
- `ai_workflow/state/`
- `ai_workflow/evaluation/`

These packages expose curated domain APIs and become the preferred internal import
surfaces for new command modules.

Do **not** mass-move every working implementation file in one PR. Existing top-level
modules remain compatible implementation locations/facades. This avoids a risky import
migration while still creating explicit dependency boundaries for future work.

### 3. Compatibility is tested, not assumed

PR-12 must preserve:
- console entry point;
- top-level package exports;
- top-level CLI command names and nested command names;
- representative parser argument behavior;
- existing legacy module imports used by tests/integrations;
- return/exit behavior of handlers.

### 4. No new dependency

Use Python packages, `argparse`, and existing code only.

## Scope

I-045 — split the oversized CLI into domain command modules.
I-046 — establish an explicit retrieval package boundary.
I-047 — establish provider/state/evaluation package boundaries.
I-048 — preserve existing CLI/import/public API through compatibility facades.

## Non-goals

- No feature changes.
- No ranking/retrieval-policy changes.
- No benchmark behavior changes.
- No storage schema changes.
- No config schema changes.
- No new CLI framework.
- No mass renaming of every top-level module.
