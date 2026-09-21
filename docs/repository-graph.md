# Workspace repository graph

AI Workflow keeps cross-repository relationships explicit. The graph is control-plane configuration; it never discovers or activates a repository by following source text, model output, provider output, or memory.

The default file is `ai-workspace/config/repository-graph.json`. Every endpoint must already be an accepted repository in `repositories.json`.

## Schema

```json
{
  "version": 1,
  "review_required": true,
  "edges": [
    {
      "source_repository_id": "<stable repository_id>",
      "target_repository_id": "<stable repository_id>",
      "relationship": "depends_on"
    }
  ]
}
```

An edge reads as **source relationship target**. Supported relationships are:

- `depends_on`: source has a build/runtime dependency on target.
- `publishes_api`: source intentionally publishes an API consumed by target.
- `consumes_schema`: source intentionally consumes a schema owned by target.
- `deploys`: source intentionally deploys or owns deployment of target.

Repository IDs come from the accepted workspace registry and are stable over checkout location changes. The graph rejects unknown/excluded endpoints, self-edges, duplicate edges, unknown relationship kinds, malformed payloads, and graph paths outside the workspace. Any such ambiguity fails closed to an empty relationship set.

PR-23 only records topology. It does not grant repository activation or automatically retrieve from neighboring repositories. Repository-first routing and bounded cross-repository expansion are handled separately.
