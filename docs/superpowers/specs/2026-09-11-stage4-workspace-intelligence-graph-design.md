# Stage 4: Deterministic Workspace Intelligence Graph

Date: 2026-09-11
Branch: research/stage4-workspace-intelligence-graph

## Status

Approved architecture. This specification converts the approved Stage 4 design into an implementation contract.

## Goal

Add an evidence-backed cross-repository structural graph that helps AI Workflow answer multi-hop architectural questions across repositories without searching every repository or introducing an LLM-generated topology.

Stage 4 augments Stage 3. Repository selection, one global context budget, per-repository retrieval, deterministic ranking, and existing safety routing remain authoritative.

## Research basis

This design follows the research direction already captured in the Deep Research Audit:

- build deterministic cross-repository intelligence after repository preselection and globally conserved budgeting;
- prefer evidence-backed repository structure over model-invented topology;
- measure structural retrieval independently from final code generation;
- keep learned routing, contextual bandits, and self-optimising topology for later shadow/offline stages.

It also follows the 2026 Repository Intelligence Graph / graph-RAG / cross-repository retrieval pattern: construct deterministic graph structure from repository artifacts, begin from strong seed nodes, and expand only a bounded neighborhood.

## Non-goals

Stage 4 does not add:

- Neo4j or any external graph database;
- embeddings as a required graph primitive;
- LLM-generated nodes or edges;
- CFG/data-flow analysis;
- learned traversal or graph neural networks;
- daemon/background indexing;
- recursive unbounded expansion;
- autonomous topology mutation;
- dependency installation at runtime;
- changes to deterministic safety/risk routing.

## Architecture

New modules:

- `ai_workflow/workspace_graph.py`: immutable graph types, IDs, serialization, fingerprinting.
- `ai_workflow/workspace_graph_builder.py`: deterministic extraction and cross-repository edge resolution.
- `ai_workflow/workspace_graph_retrieval.py`: seed resolution, bounded expansion, scoring, context conversion.
- `ai_workflow/workspace_graph_metrics.py`: graph benchmark metrics.

Existing integrations:

- `workspace_selector.py`: unchanged authority for repository preselection.
- `workspace_retrieval.py`: optional graph augmentation after repository selection, before final global packing.
- `cli.py`: additive graph diagnostics.
- `benchmark.py`: additive graph metrics when gold graph labels are present.
- `config.py` / setup defaults: additive Stage 4 graph settings.
- `.github/workflows/tests.yml`: graph modules added to focused Ruff/Mypy gates.

Persisted files remain inside the single workspace directory:

```text
ai-workspace/generated/
  workspace-graph-nodes.jsonl
  workspace-graph-edges.jsonl
  workspace-graph-state.json
```

No child repository receives its own control-plane directory.

## Graph model

### Node

```text
GraphNode
  node_id
  kind
  repository_id
  repository_path
  path
  symbol
  label
  fingerprint
  evidence
```

Required node kinds for the MVP:

- repository
- file
- symbol
- endpoint
- package
- test

### Edge

```text
GraphEdge
  edge_id
  edge_type
  source_node_id
  target_node_id
  source_repository_id
  target_repository_id
  evidence_path
  evidence_line
  extractor
  confidence
  fingerprint
```

Required edge types for the MVP:

- CONTAINS
- IMPORTS
- DEPENDS_ON
- CALLS_API
- IMPLEMENTS_ENDPOINT
- TESTS

The graph may contain same-repository and cross-repository edges. Cross-repository edges are first-class and must keep both repository IDs.

## Deterministic identity

Node IDs and edge IDs are SHA-256 derived from portable canonical fields.

Absolute checkout paths MUST NOT participate in IDs or persisted graph payloads.

Node ID input:

```text
schema_version | kind | repository_id | portable_path | symbol_or_label
```

Edge ID input:

```text
schema_version | edge_type | source_node_id | target_node_id | evidence_key
```

Serialization order is deterministic:

- nodes: `(repository_id, kind, path, symbol, node_id)`
- edges: `(source_node_id, edge_type, target_node_id, evidence_path, edge_id)`

## Evidence policy

Every non-CONTAINS edge requires direct deterministic evidence.

Allowed MVP evidence:

- Python/JS/TS/Go import statements;
- `pyproject.toml`, `requirements*.txt`, `package.json`, `go.mod` dependencies;
- endpoint index rows already produced by AI Workflow;
- literal HTTP route/path usage in source;
- conventional test-to-source naming relationships.

No fuzzy semantic edge is persisted.

`confidence` is extractor confidence, not model probability:

- 1.0: exact manifest/import/index relationship
- 0.9: exact literal endpoint/client path match
- 0.8: deterministic test/source naming relationship

No edge below 0.8 is persisted in Stage 4.

## Extractors

### Repository/file containment

Create repository and file nodes only for active repositories and their indexed source files. Discovered-but-inactive repositories are excluded from persisted graph state entirely.

### Imports

Use lightweight language-aware regex/AST-safe parsing where already available:

- Python: `import x`, `from x import y`
- JS/TS: `import ... from "x"`, `require("x")`
- Go: import block and single import paths

Resolve an import to another workspace repository only when a deterministic package/module identity maps exactly.

### Package dependencies

Read local package identities and declared dependencies from:

- Python project metadata;
- package.json name/dependencies/devDependencies;
- go.mod module/require.

A local workspace dependency creates `DEPENDS_ON`.

### HTTP relationships

Use existing endpoint-index rows as endpoint nodes.

Literal client references to the same normalized route create `CALLS_API`.

Endpoint index ownership creates `IMPLEMENTS_ENDPOINT` from file/symbol to endpoint.

Dynamic routes that cannot be normalized exactly are skipped.

### Tests

Create `TESTS` only from deterministic naming/path conventions already supported by the codebase. No semantic guessing.

## Graph build and invalidation

`build_workspace_graph(workspace_root, config)` produces nodes, edges, and state.

State includes:

- schema_version;
- aggregate workspace fingerprint;
- per-repository fingerprints;
- graph fingerprint;
- node_count;
- edge_count;
- extractor_version.

If aggregate workspace fingerprint and extractor version are unchanged, the persisted graph is reusable.

If one repository fingerprint changes:

- rebuild nodes/edges owned by that repository;
- invalidate cross-repository edges whose source or target repository is that repository;
- re-resolve only affected cross-repository relationships.

The MVP may implement this as logically incremental recomposition rather than an in-place graph mutation, provided unchanged repository extraction can be reused from the persisted graph.

Malformed graph state fails closed: graph augmentation is skipped or rebuilt; retrieval must continue through Stage 3.

## Query-time graph retrieval

Graph retrieval occurs only after Stage 3 repository selection.

Seeds come from:

1. explicitly requested symbol/endpoint;
2. Stage 3 retrieved context item paths/symbols;
3. changed files;
4. selected repository identities.

Graph expansion defaults:

- max_hops: 2
- max_nodes: 24
- max_edges: 40
- max_context_chars: 3000
- min_edge_confidence: 0.8

The graph budget is a cap inside the existing parent context budget. It is NOT additional context and is not pre-reserved. Graph items and Stage 3 repository items enter the same final deterministic pack, whose total characters remain bounded by the original parent `ContextBudget.context_chars`.

Expansion must be deterministic and breadth-bounded.

No graph traversal may activate an unaccepted repository. A graph edge into an inactive repository is ignored.

## Graph scoring

Use a deterministic score:

```text
score =
  4.0 * query_overlap
+ 3.0 * seed_match
+ 2.0 * changed_file_match
+ 2.0 * cross_repo_bonus
+ 1.0 * edge_confidence
- 1.5 * graph_distance
```

Tie-break by:

```text
(-score, distance, repository_id, kind, path, node_id)
```

No random factors and no completion-order dependence.

## Integration with Stage 3

The Stage 3 flow becomes:

```text
task
  -> deterministic lane/risk routing
  -> accepted repository candidates
  -> repository preselection
  -> global budget allocation
  -> per-repository retrieval
  -> graph seed resolution
  -> bounded graph expansion
  -> graph evidence converted to ContextItem
  -> one deterministic global pack
```

Graph evidence has source `workspace_graph`.

Its metadata/provenance includes:

- repository_id
- repository_path
- repository_fingerprint when available
- graph_node_id
- graph_edge_ids
- graph_distance
- graph_fingerprint
- evidence_path

Graph evidence is deduplicated by graph identity, not text alone.

## Error handling

Graph is an optional structural accelerator.

- Missing graph: build if allowed; otherwise continue Stage 3 retrieval.
- Corrupt graph: ignore/rebuild and record diagnostics.
- Extractor failure for one file: skip that file and record a bounded warning.
- Unsupported language/artifact: ignore.
- Deadline exhaustion: stop expansion and keep already-ranked graph evidence.
- No graph seed: no graph context is added.

Graph errors must not fail the overall `brief` or `context` command.

## Configuration

Add:

```json
"workspace": {
  "graph": {
    "enabled": true,
    "max_hops": 2,
    "max_nodes": 24,
    "max_edges": 40,
    "max_context_chars": 3000,
    "min_edge_confidence": 0.8,
    "build_on_demand": true
  }
}
```

Validation is typed and bounded:

- max_hops: 1..3
- max_nodes: 1..100
- max_edges: 1..200
- max_context_chars: 256..12000
- min_edge_confidence: 0.0..1.0

Existing configs without `workspace.graph` receive the defaults.

## CLI

Add:

```text
ai-workflow graph build
ai-workflow graph status
```

Both produce deterministic JSON.

`brief` and `context` add an optional `retrieval.workspace_graph` diagnostic block:

```json
{
  "enabled": true,
  "graph_fingerprint": "...",
  "seed_nodes": 4,
  "expanded_nodes": 13,
  "expanded_edges": 18,
  "cross_repo_edges": 5,
  "hops_used": 2,
  "repositories_reached": ["backend", "frontend"],
  "budget": {
    "allocated_context_chars": 2400,
    "used_context_chars": 1810
  }
}
```

Single-repository behavior remains compatible.

## Benchmarks

Add graph metrics only when gold graph labels are provided:

- `graph_node_recall_at_k`
- `cross_repo_edge_recall`
- `wrong_edge_rate`
- `structural_recall_at_k`
- `graph_context_yield`

Definitions:

```text
GraphNodeRecall@K = relevant graph nodes in top K / gold graph nodes

CrossRepoEdgeRecall = retrieved gold cross-repo edges / gold cross-repo edges

WrongEdgeRate = retrieved non-gold edges / retrieved edges

StructuralRecall@K = relevant structural evidence in top K / gold structural evidence

GraphContextYield = useful graph evidence chars / delivered graph chars
```

Add an adversarial multi-repository fixture containing at least:

- 10 repositories;
- duplicate file names;
- duplicate symbol names;
- same route string in unrelated repos;
- one true frontend -> backend endpoint path;
- one local package dependency;
- one test relationship;
- inactive repository with tempting matching evidence.

Benchmarks must compare graph-enabled and graph-disabled retrieval without changing the existing Stage 3 regression baseline.

## Security and trust

Repository content is untrusted evidence.

Graph nodes/edges never grant execution capability and never change repository activation.

Persisted graph data:

- contains no credentials;
- contains no raw remote URL credentials;
- contains no absolute checkout paths;
- does not execute manifest scripts;
- does not import repository Python modules;
- does not run package managers.

Only static text parsing is allowed in the MVP.

## Quality gates

Stage 4 is done only when:

- new graph tests are red before implementation and green after;
- full unit suite passes;
- Ruff passes for all Stage 4 modules;
- Mypy passes for all Stage 4 modules;
- existing benchmark regression gate passes unchanged;
- graph benchmarks pass their new deterministic fixtures;
- package smoke passes;
- Ubuntu Python 3.10-3.14 pass;
- Windows Python 3.14 passes;
- macOS Python 3.14 passes;
- graph output is deterministic across repeated builds;
- absolute-path relocation does not change graph identity;
- inactive repositories cannot be reached through graph expansion.

## Self-review resolution

- No placeholders or TBD requirements remain.
- Inactive repositories are excluded at graph-build time and cannot be activated by traversal.
- Graph context has no additive budget; Stage 3's parent budget remains the single hard ceiling.
- Incremental invalidation may recompose the graph from persisted unchanged repository fragments, but correctness must not depend on in-place mutation.

## Delivery

Implementation branch:

`research/stage4-workspace-intelligence-graph`

Final pull request target:

`research/stage3-multi-repo-retrieval`

The PR is not merged automatically.
