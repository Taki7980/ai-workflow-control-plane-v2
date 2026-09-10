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

Raw remote URLs are not part of the persisted registry contract. A remote such as `https://user:token@github.com/acme/backend.git` is normalized to the credential-free identity `github.com/acme/backend` before anything is written.

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

`repos refresh` performs discovery again and atomically rewrites the registry. An explicit inclusion decision is preserved only when both the repository path and remote identity are unchanged. If the same path now points to a different remote identity, it returns to `included: false` and must be reviewed again.

Newly discovered repositories are always excluded by default.

## Why acceptance is required

Multi-repo folders are easy to confuse: sibling repositories may have different remotes, branches, credentials, worktrees, owners, release pipelines, and instructions. Repository-level retrieval can become actively harmful when context comes from the wrong repository, so the safe default is discovery without execution.

The registry model follows these rules:

- persist workspace-relative repository paths rather than absolute checkout locations;
- persist normalized remote identity, never raw remote URLs or embedded credentials;
- keep per-repository boundaries explicit;
- require explicit inclusion before a discovered sibling becomes an active workspace root;
- reject registry-controlled absolute paths, parent traversal, and symlink escapes;
- require an activated registry path to still be a Git repository;
- cap active roots with `workspace.max_roots`;
- preserve existing registries during `setup` so user decisions are not overwritten;
- support Git worktrees by reading their `gitdir:` pointer;
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

The aggregate workspace fingerprint hashes the active repository snapshots in deterministic order. Absolute checkout paths are returned for diagnostics but are excluded from the hashed identity, so moving an otherwise identical workspace does not change its aggregate fingerprint.

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
- a Git worktree with `.git` as a file;
- credential-bearing remote URLs that must never be persisted raw;
- unaccepted repositories that must not become workspace roots;
- accepted repositories capped by `workspace.max_roots`;
- registry path traversal, absolute-path, and symlink-escape attempts;
- ambiguous repository names that must fail without writes;
- repository identity changes that reset prior inclusion;
- path-independent aggregate workspace fingerprints;
- dirty tracked and untracked content that changes repository fingerprints;
- legacy `workspace.roots` compatibility;
- malicious nested folders such as `node_modules/.git` that must be skipped.
