# Source and release governance

This document defines the repository-administration controls required to protect AI Workflow source and release authority. These controls address the source/tag governance gap identified by the security research review.

Repository files alone cannot enforce GitHub branch, tag, or environment protection. The settings below are mandatory repository-administration controls and must be verified in GitHub after changes to repository ownership or release automation.

## `main` ruleset

Target the default branch `main` and require:

- changes through pull requests;
- at least one approval;
- CODEOWNERS review for owned paths;
- dismissal of stale approvals when new commits are pushed;
- successful required status checks before merge;
- the branch to be up to date before merge when GitHub supports it for the selected checks;
- no force pushes;
- no branch deletion;
- no ordinary bypass identity.

The required checks should include every blocking job from `.github/workflows/tests.yml`. Security-specific checks will be added in the dedicated security-CI stage and should then be added to this ruleset.

## Release tag ruleset

Target `v*` tags and require:

- creation only by release-maintainer authority;
- no tag update after creation;
- no tag deletion except documented break-glass recovery;
- release tags to point at reviewed source from `main`.

The release workflow is intentionally triggered only by `v*` tags.

## Protected environments

### `release`

`.github/workflows/release.yml` routes the initial release gate through the `release` environment. Configure that environment with:

- required reviewer approval;
- deployment branches/tags restricted to protected `v*` release tags;
- no long-lived publishing secret.

All publishing jobs depend on the approved `prepare-release` job.

### `pypi`

Keep the existing `pypi` environment protected. PyPI publication uses GitHub OIDC Trusted Publishing and should not store a PyPI upload token.

## CODEOWNERS

`.github/CODEOWNERS` assigns the repository owner to workflows, release inputs, installers, provider execution, telemetry, deployment policy, learning verification, and provenance code. The `main` ruleset must require CODEOWNERS review; the file by itself is advisory.

## Verification

F-02 is considered closed only when all of the following are true:

1. `main` reports protected or an active ruleset applies equivalent controls.
2. A repository ruleset protects `main`.
3. A tag ruleset protects `v*`.
4. CODEOWNERS review is required for sensitive paths.
5. The `release` environment requires approval and is restricted to protected release tags.
6. The `pypi` environment remains protected.
7. Direct-push, force-push, branch-deletion, and unauthorized release-tag bypass attempts are rejected.
