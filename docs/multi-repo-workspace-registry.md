# Multi-repo workspace registry

AI Workflow now treats a project folder as a workspace that may contain one or more local Git repositories. Setup creates control-plane files inside a single top-level `ai-workspace/` folder by default.

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

`ai-workflow setup` performs read-only discovery for `.git` directories and Git worktree `.git` files. It does not run Git commands, does not use credentials, and does not enable discovered repositories automatically.

The registry lives at `ai-workspace/config/repositories.json`:

```json
{
  "version": 1,
  "review_required": true,
  "repositories": [
    {
      "name": "backend",
      "relative_path": "backend",
      "remote_identity": "github.com/acme/backend",
      "head_ref": "refs/heads/main",
      "head_sha": "...",
      "included": false,
      "reason": "discovered"
    }
  ]
}
```

Set `included: true` only after reviewing the discovered repository boundary. The control plane ignores unaccepted repositories, even if they exist under the same parent folder.

## Why acceptance is required

Multi-repo folders are easy to confuse: sibling repositories may have different remotes, branches, credentials, worktrees, owners, release pipelines, and instructions. Research on repository-level retrieval and coding agents shows that wrong or stale context is a real failure mode, so the safe default is discovery without execution.

The registry model follows these rules:

- use relative paths only in persisted state;
- hash or normalize remote identity without storing credentials;
- keep per-repo boundaries explicit;
- cap active roots with `workspace.max_roots`;
- preserve existing registries during setup so user review is not overwritten;
- support Git worktrees by reading their `gitdir:` pointer;
- keep generated state and handoffs inside `ai-workspace/`.

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

`workspace.roots` remains as a backward-compatible escape hatch. The registry is the preferred path for new workspaces.

## Commands

```bash
ai-workflow setup
ai-workflow setup --no-discover-repos
ai-workflow setup --discover-depth 2
ai-workflow setup --legacy-root-files
ai-workflow brief "change auth callback" --write-handoff
ai-workflow handoff validate
```

## Testing expectations

A multi-repo fixture should include at least:

- parent folder with no Git repo;
- parent folder that is itself a Git repo;
- sibling `frontend` and `backend` repos with different remotes;
- a Git worktree with `.git` as a file;
- unaccepted repositories that must not become workspace roots;
- accepted repositories capped by `workspace.max_roots`;
- legacy `workspace.roots` compatibility;
- malicious nested folders such as `node_modules/.git` that must be skipped.
