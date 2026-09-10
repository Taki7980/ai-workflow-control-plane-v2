# Multi-repo workspace registry

AI Workflow treats a project folder as a workspace that may contain one or more local Git repositories. Setup creates control-plane files inside a single top-level `ai-workspace/` folder by default.

## Default layout

```text
project-root/
  frontend/        # optional local Git repo
  backend/         # optional local Git repo
  ai-workspace/
    agents/AGENTS.md
    config/control-plane.json
    config/repositories.json
    generated/
    handoff/
    state/PROJECT
```

Root-level `AGENTS.md` and `.ai/` are no longer created by default. They are still supported for old projects and can be emitted with `ai-workflow setup --legacy-root-files`.

## Repository discovery

`ai-workflow setup` performs read-only discovery for `.git` directories and Git worktree `.git` files. It does not invoke Git during discovery and does not enable discovered repositories automatically.

The registry lives at `ai-workspace/config/repositories.json`:

```json
{
  "version": 1,
  "review_required": true,
  "repositories": [
    {
      "repository_id": "...",
      "name": "backend",
      "relative_path": "backend",
      "git_dir": "backend/.git",
      "remote_identity": "github.com/acme/backend",
      "head_ref": "refs/heads/main",
      "head_sha": "...",
      "included": false,
      "reason": "discovered"
    }
  ]
}
```

Raw remote URLs are not part of the persisted registry contract. A remote such as `https://user:token@github.com/acme/backend.git` is normalized to the credential-free identity `github.com/acme/backend` before anything is written. The remote host is normalized to lowercase, while the repository path preserves its original casing so case-sensitive Git servers cannot collapse distinct repository identities.

Each repository also gets a deterministic `repository_id` derived from its workspace-relative path and normalized remote identity. This gives automation a stable selector without storing an absolute checkout path.

## Review and activation workflow

Do not edit `repositories.json` by hand for normal operation. Use the repository-management commands:

```bash
ai-workflow repos list
ai-workflow repos refresh
ai-workflow repos include backend
ai-workflow repos exclude backend
```

`include` and `exclude` accept an exact workspace-relative path, repository ID, remote identity, or unique repository name. An ambiguous name fails without changing the registry.

`review_required` is a fail-closed trust gate: a registry is accepted only when the field is present and exactly `true`. Missing, false, malformed, unsupported, or ambiguous registry state is ignored for repository activation. `repos refresh` is the explicit recovery path.

`repos refresh` performs discovery again and atomically rewrites the registry. An explicit inclusion decision is preserved only when both the repository path and remote identity are unchanged. If the same path now points to a different remote identity, it returns to `included: false` and must be reviewed again.

Older Stage 2 registries may contain fully lowercased remote identities. After upgrading, `repos refresh` migrates to host-only case normalization. If preserving the remote path casing changes the repository identity, prior inclusion is intentionally reset and must be accepted again rather than silently carrying an ambiguous legacy decision forward.

Registry read-modify-write operations are serialized across processes with a persistent sidecar lock next to `repositories.json`. Readers remain lock-free because registry replacement is atomic, while concurrent `refresh`, `include`, and `exclude` writers cannot overwrite each other's decisions.

Newly discovered repositories are always excluded by default.

## Why acceptance is required

Multi-repo folders are easy to confuse: sibling repositories may have different remotes, branches, credentials, worktrees, owners, release pipelines, and instructions. Repository-level retrieval can become actively harmful when context comes from the wrong repository, so the safe default is discovery without execution.

The registry model follows these rules:

- persist workspace-relative repository paths rather than absolute checkout locations;
- persist normalized remote identity, never raw remote URLs or embedded credentials;
- normalize remote hosts but preserve remote path casing;
- require `review_required: true` before registry entries can activate repositories;
- serialize registry writers so concurrent commands cannot lose accepted/excluded decisions;
- keep per-repository boundaries explicit;
- require explicit inclusion before a discovered sibling becomes an active workspace root;
- reject registry-controlled absolute paths, parent traversal, and symlink escapes;
- require an activated registry path to still be a Git repository;
- cap active roots with `workspace.max_roots`;
- preserve existing registries during `setup` so user decisions are not overwritten;
- support Git worktrees by reading their `gitdir:` pointer and shared Git metadata;
- keep generated state and handoffs inside `ai-workspace/`.

Malformed or unsupported registry files fail closed for repository activation. Running `repos refresh` is the explicit recovery path when local repository discovery should rebuild the registry.

## Workspace identity

Stage 2 adds per-repository and aggregate workspace fingerprints.

A repository fingerprint includes stable identity plus current Git/worktree evidence:

- deterministic repository ID and workspace-relative path;
- normalized remote identity;
- current Git HEAD and branch/ref when available;
- content-sensitive tracked and untracked worktree state;
- optional index-state digest;
- explicitly supplied changed-file hashes.

The aggregate workspace fingerprint hashes the active repository snapshots in deterministic total order. Repository fingerprint is used as a final tie-breaker when legacy roots otherwise share the same synthetic identity, so reversing equivalent input-root order cannot change the aggregate fingerprint. Absolute checkout paths are returned for diagnostics but are excluded from the hashed identity, so moving an otherwise identical workspace does not change its aggregate fingerprint.

The original single-root `workspace_fingerprint()` contract remains supported for compatibility.

## Configuration

`ai-workspace/config/control-plane.json` contains:

```json
"workspace": {
  "roots": [],
  "max_roots": 4,
  "registry": "ai-workspace/config/repositories.json",
  "discovery": {
    "max_depth": 3,
    "require_acceptance": true
  }
}
```

`workspace.roots` remains as a backward-compatible escape hatch. Registry-controlled roots are the preferred path for new multi-repo workspaces because they receive the stricter confinement and explicit acceptance checks.

## Commands

```bash
# Initialize/update the workspace
ai-workflow setup
ai-workflow setup --no-discover-repos
ai-workflow setup --discover-depth 2
ai-workflow setup --legacy-root-files

# Review and manage repositories
ai-workflow repos list
ai-workflow repos refresh
ai-workflow repos refresh --discover-depth 2
ai-workflow repos include backend
ai-workflow repos exclude backend

# Normal workflow
ai-workflow brief "change auth callback" --write-handoff
ai-workflow handoff validate
```

All `repos` commands produce deterministic JSON suitable for scripts and agents.

## Testing expectations

A multi-repo fixture should include at least:

- parent folder with no Git repo;
- parent folder that is itself a Git repo;
- sibling `frontend` and `backend` repos with different remotes;
- a Git worktree with `.git` as a file and shared remote metadata;
- credential-bearing remote URLs that must never be persisted raw;
- case-sensitive remote paths that must remain distinct;
- `review_required` values that must fail closed unless exactly true;
- concurrent registry writers that must serialize;
- unaccepted repositories that must not become workspace roots;
- accepted repositories capped by `workspace.max_roots`;
- registry path traversal, absolute-path, and symlink-escape attempts;
- ambiguous repository names that must fail without writes;
- repository identity changes that reset prior inclusion;
- path-independent and input-order-independent aggregate workspace fingerprints;
- dirty tracked and untracked content that changes repository fingerprints;
- legacy `workspace.roots` compatibility;
- malicious nested folders such as `node_modules/.git` that must be skipped.


## Stage 3 retrieval orchestration

Accepted repositories are retrieval **candidates**, not repositories that are searched automatically. `brief` and `context` score the accepted candidate set deterministically and search at most three repositories by default. A strong secondary-repository signal can outrank the primary repository; unrelated accepted repositories remain skipped.

All selected repositories share one parent context budget. The rank-1 repository receives the strongest allocation, per-repository slices are bounded, and the sum of allocations and final merged evidence never exceeds the parent budget. Repository retrieval runs with at most three workers under one 12-second monotonic workspace deadline by default. A timed-out or failed repository is reported and is not retried or replaced by an unselected repository.

Changed files are partitioned to their owning repository before repository-local retrieval. Every merged context item carries portable `repository_id`, `repository_path`, and `repository_fingerprint` provenance; absolute checkout paths are not serialized into portable evidence. Identical evidence text from two repositories remains distinct because cross-repository deduplication includes repository identity.

`ai-workflow brief` and `ai-workflow context` preserve the existing retrieval fields and add `retrieval.workspace_orchestration`. That block reports the aggregate workspace fingerprint, selected and skipped repositories with selector reasons, per-repository status, context allocation and use, and scheduler/deadline diagnostics. Human-readable briefs show selected/skipped repository paths and the aggregate repository budget only when the workspace has multiple candidates.

Stage 3 intentionally does not add dependency-graph traversal, topology learning, learned routing, daemon behavior, or retry loops. Those remain later-stage work.


## Stage 4 workspace intelligence graph

Stage 4 adds a deterministic, evidence-backed structural graph for accepted multi-repository workspaces. The graph augments Stage 3 retrieval; it does not replace repository selection, repository acceptance, risk routing, or the parent context budget.

Graph state remains inside the single top-level workspace:

```text
ai-workspace/generated/
  workspace-graph-nodes.jsonl
  workspace-graph-edges.jsonl
  workspace-graph-state.json
```

Only active repositories are represented. Discovered-but-excluded repositories are not written into graph state and cannot be reached through graph expansion.

The MVP builds nodes for repositories, files, packages, endpoints, symbols, and tests. Edges are persisted only when static repository evidence supports them:

- `CONTAINS` for repository ownership;
- `IMPORTS` for exact local package/module imports;
- `DEPENDS_ON` for exact local manifest dependencies;
- `IMPLEMENTS_ENDPOINT` from the existing endpoint index;
- `CALLS_API` from literal HTTP client calls resolved to one unambiguous endpoint, using HTTP method evidence when available;
- `TESTS` from deterministic test/source naming conventions.

Repository content is treated as untrusted text. Graph construction does not import project modules, execute manifest scripts, run package managers, call an LLM, or install a graph database. Absolute checkout paths and credential-bearing remote URLs are excluded from portable graph identity and persisted evidence.

Build or inspect graph state with:

```bash
ai-workflow graph build
ai-workflow graph status
```

Graph retrieval begins from Stage 3-selected repository evidence, explicit symbols/endpoints, changed files, or repository seeds. Expansion is deterministic and bounded by default to two hops, 24 nodes, 40 edges, a minimum extractor confidence of 0.8, and at most 3000 graph-context characters. Those 3000 characters are only an internal graph cap: graph evidence competes with Stage 3 evidence inside the original parent `ContextBudget.context_chars`; it never creates additional context budget.

A single-repository workspace keeps the existing Stage 3 retrieval path and reports graph status `single_repository`. In a multi-repository workspace, Stage 4 may still expand graph context when Stage 3 selected only one relevant repository, but traversal is confined to repository IDs permitted by the Stage 3 selection boundary. A missing, stale, corrupt, or failed graph is an optional-acceleration failure and does not discard successful Stage 3 evidence.

Graph-derived context uses source `workspace_graph` and carries portable provenance including repository ID/path/fingerprint, graph node ID, traversed edge IDs, graph distance, graph fingerprint, and evidence path. The benchmark harness supports graph-node recall, cross-repository edge recall, wrong-edge rate, structural recall, and graph-context yield when corresponding gold labels are supplied.

Stage 4 intentionally does not add LLM-generated topology, embeddings as a required primitive, Neo4j or another graph database, control-flow/data-flow graphs, learned traversal, graph neural networks, autonomous topology mutation, or background daemon indexing.
