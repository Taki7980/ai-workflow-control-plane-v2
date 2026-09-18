# PR-10 — SCIP Multilingual Structural Indexing Research

Date: 2026-09-18
Tracks: I-037 through I-040

## Repository fit

AI Workflow already has three relevant layers:

1. `indexer.py` builds the dependency-free lightweight symbol/endpoint index.
2. `WorkflowEngine` owns specialist retrieval and structural expansion.
3. `code_review_graph.py` provides optional precise structural evidence with explicit freshness and fallback behavior.

SCIP therefore belongs as an optional structural provider inside the existing WorkflowEngine boundary. It must not replace the lightweight index, CRG, ranking, or context-selection layers.

## External evidence

- SCIP is a language-agnostic code-intelligence protocol for definitions, references, and implementations:
  https://github.com/scip-code/scip
- Sourcegraph documents precise SCIP navigation with search-based fallback when a precise index is unavailable:
  https://sourcegraph.com/docs/code-navigation/precise-code-navigation
- Current recommended indexers are generally available for Go, TypeScript/JavaScript, Java, and Python:
  https://sourcegraph.com/docs/code-navigation/writing-an-indexer
- Agent Retrieval Bench reports that no single retrieval family dominates and that structural RepoMap evidence can lead on budgeted context yield:
  https://arxiv.org/abs/2607.24882

## Design decision

Keep the Python package dependency-free. Do not vendor SCIP protobuf bindings.

Consume SCIP through the official CLI JSON boundary:

```
scip print --json <index.scip>
```

Language-specific indexers remain external tools:

- Go: `scip-go`
- TypeScript: `scip-typescript index`
- JavaScript: `scip-typescript index --infer-tsconfig`
- Java: `scip-java index`
- Python: `scip-python index . --project-name <name>`

## Safety/freshness rules

- SCIP is optional.
- Automatic retrieval only uses an existing central index whose manifest matches the current repository fingerprint and Git HEAD.
- Index generation is explicit, not silently triggered during retrieval.
- Missing tools, missing index, stale provenance, invalid JSON, timeout, or indexer failure fall back to CRG/lightweight retrieval.
- Generated SCIP artifacts stay below `ai-workspace/scip/`, never beside source repositories.
- No shell invocation.

## Benchmark gate

Extend the existing provider-family ablation suite with `base_scip`. The same frozen research cases introduced before PR-10 can compare SCIP against the existing adaptive/base/semantic/CRG families. This prevents retaining complexity merely because SCIP exists.

## Scope

I-037 — optional first-class SCIP structural provider.
I-038 — deterministic adapters for Python, TypeScript/JavaScript, Java, and Go.
I-039 — provenance-bound freshness plus graceful fallback.
I-040 — existing benchmark ablation support for SCIP.
