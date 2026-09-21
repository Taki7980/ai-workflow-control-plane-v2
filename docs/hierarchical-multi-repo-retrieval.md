# Hierarchical multi-repository retrieval

AI Workflow retrieves repository-first. It does not search every accepted repository merely because those repositories share a workspace.

## Routing order

1. **Primary repository** — changed-file ownership is the strongest routing signal. An explicit repository name/path in the task is the next signal. If neither is available, retrieval stays on the first local repository.
2. **Reviewed graph expansion** — the router may add a bounded one-hop neighbor from the reviewed repository graph.
3. **Hybrid retrieval inside selected repositories** — existing lexical, semantic, CRG, SCIP, and source retrieval operate only on the selected roots.
4. **Global context selection** — the existing context/token budget remains the hard limit.

Graph-expanded evidence receives a lower deterministic prior than evidence from a primary repository. This makes repository topology a relevance hint, not authority.

## Configuration

```json
{
  "workspace": {
    "max_roots": 4,
    "hierarchical_retrieval": {
      "enabled": true,
      "max_primary_repositories": 2,
      "max_graph_expansions": 2,
      "relationships": [
        "depends_on",
        "publishes_api",
        "consumes_schema",
        "deploys"
      ]
    }
  }
}
```

`max_roots` remains the final hard cap. `max_graph_expansions` can only reduce graph fan-out; it cannot bypass `max_roots`.

## Fail-closed behavior

A missing, malformed, unreviewed, or stale-by-identity repository graph grants no expansion. Unknown and excluded repositories cannot be routed through the graph. Repository text, model output, memory, and external retrieval providers cannot create graph edges.

Legacy explicitly configured `workspace.roots` without registry identities retain their historical behavior for compatibility. They do not participate in graph expansion.

## Diagnostics

Each retrieval reports `repository_routing` with the graph fingerprint, primary repository IDs, expanded repository IDs, skipped repository IDs, routing tier, relationship, prior, and routing reason. This makes cross-repository context expansion auditable without logging repository content.
