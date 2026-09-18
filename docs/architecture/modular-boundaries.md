# Modular Architecture

AI Workflow keeps its stable external surfaces while organizing new internal work
behind explicit domain boundaries.

## Stable compatibility surfaces

These remain supported:

- Console entry point: `ai-workflow = ai_workflow.entrypoint:main`
- Package exports: `TaskRequest`, `WorkflowClient`, `WorkflowResult`,
  `prepare`, and `__version__`
- Existing top-level modules such as `ai_workflow.cli`,
  `ai_workflow.workflow_engine`, `ai_workflow.providers`,
  `ai_workflow.provenance`, and benchmark modules
- Existing CLI command and subcommand names

PR-12 does not introduce deprecation warnings because these paths remain valid
compatibility facades.

## Preferred internal boundaries

New code should prefer the narrowest applicable domain API:

- `ai_workflow.retrieval` — retrieval planning, sufficiency, gathering, and
  orchestration
- `ai_workflow.provider` — provider detection and execution/model selection
- `ai_workflow.state` — provenance, telemetry, workspace identity, and run
  journals
- `ai_workflow.evaluation` — benchmark, ablation, intervention, calibration,
  and statistics entry points
- `ai_workflow.commands` — CLI-only command handlers and parser registration

## Dependency direction

```
entrypoint
   |
   v
compatibility CLI facade
   |
   v
commands/*
   |
   +--> retrieval
   +--> provider
   +--> state
   +--> evaluation
   |
   v
existing focused implementation modules
```

Domain packages are curated import surfaces, not duplicated implementations.
Existing implementation modules remain authoritative until a future change has a
measured reason to move them.

## Refactoring rule

Internal organization may change only when external behavior stays covered by
compatibility tests. The following are treated as contracts:

- CLI command names and parser behavior
- package exports
- console entry point
- supported legacy import paths
- return values, side effects, and established error/exit behavior

This follows the compatibility-first approach described in PEP 387 and avoids a
mass import migration during a behavior-preserving refactor.
