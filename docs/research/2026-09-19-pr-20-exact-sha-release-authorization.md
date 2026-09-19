# PR-20 — Exact-SHA Release Authorization Gate

Date: 2026-09-19

## Goal

A version tag is not sufficient authority to publish.

PR-20 requires a release tag to resolve to an exact source commit that is still reachable from the authorized release branch, requires that branch to be protected, and requires the project's production verification workflows to have succeeded for that exact commit before publishing can begin.

## Research basis

### GitHub required-status-check semantics

https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/troubleshooting-required-status-checks

GitHub documents that required checks must pass before protected-branch updates and that checks from an earlier commit do not satisfy a requirement for the latest commit SHA.

PR-20 applies the same identity rule to releases: a successful check from another commit, PR merge ref, or branch is not accepted as release authorization.

### GitHub workflow-runs API

https://docs.github.com/en/rest/actions/workflow-runs

Workflow-run queries can be narrowed by branch, event, head SHA, and status. PR-20 queries each required workflow directly and then independently validates the returned run fields.

Required workflows:

- `.github/workflows/tests.yml`
- `.github/workflows/security.yml`
- `.github/workflows/codeql.yml`

A valid run must have:

- `event == push`
- `head_branch == main`
- `head_sha == tagged release SHA`
- `status == completed`
- `conclusion == success`
- exact expected workflow path

### GitHub environments

https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments

https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments

GitHub environments can gate deployment jobs before protected environment secrets or privileged deployment execution become available.

PR-20 performs automated release authorization before the `release` environment gate, then repeats the authorization after approval immediately before draft creation. This avoids treating a possibly stale pre-approval result as permanent authorization.

### GitHub artifact attestations

https://docs.github.com/en/actions/concepts/security/artifact-attestations

GitHub artifact attestations bind build provenance to repository, workflow, commit SHA, event, and related OIDC identity.

PR-20 retains the project's existing attestations and strengthens post-publication verification with exact source and signer constraints.

### GitHub CLI attestation verification

https://cli.github.com/manual/gh_attestation_verify

`gh attestation verify` supports:

- `--source-digest`
- `--source-ref`
- `--signer-workflow`

PR-20 uses all three. Verification therefore requires not only the expected repository but also the exact source commit, exact tag ref, and exact release workflow signer.

### SLSA provenance

https://slsa.dev/spec/v1.2/provenance

SLSA provenance is intended to trace an artifact back through its build process to source identity. PR-20 treats release authorization as a source-to-publication control: the release may only proceed from a source revision whose identity and verification evidence have been established before artifact publication.

## Current repository finding

Live inspection on 2026-09-19 showed:

- current `main`: `c393d88eaf354d3432ef498fe970923e792ac482`
- GitHub branch API: `protected=false`
- repository rulesets: none
- the exact current main SHA had successful push runs for:
  - Tests
  - Security
  - CodeQL

This means the CI half of the intended release policy exists, but branch protection is not currently an enforcement boundary.

PR-20 intentionally fails closed when `main` is not protected. A release will not publish until repository administration enables branch protection or an equivalent active ruleset that causes GitHub to report `main` as protected.

Detailed branch-protection inspection is not delegated to the release workflow because GitHub's branch-protection REST endpoint requires Administration-read permission. The ordinary branch endpoint exposes the boolean protected state using normal repository read access, which is sufficient for the runtime fail-closed precondition without expanding release-token privilege.

## Authorization algorithm

For a tag-triggered release:

1. fetch the current remote `main`;
2. fetch the current remote tag;
3. resolve the tag to its commit;
4. require tag commit == `GITHUB_SHA`;
5. require the tag commit to be an ancestor of remote `main`;
6. query GitHub's branch object and require `main.protected == true`;
7. query each required workflow for `head_sha=GITHUB_SHA`, `branch=main`, `event=push`;
8. require a completed successful exact-path run for all required workflows;
9. emit machine-readable authorization evidence.

Any missing or malformed prerequisite denies the release.

## Two authorization points

### Pre-environment

`authorize-release` has only:

- `contents: read`
- `actions: read`

It cannot publish.

Its purpose is to reject unauthorized tags before requesting release-environment approval.

### Post-environment

`prepare-release` depends on `authorize-release` and uses the existing protected `release` environment.

After approval, it runs the exact same authorization again before:

- creating/reusing the draft release;
- attaching assets;
- enabling downstream publishing jobs.

This protects against tag/branch state changes during an approval delay.

## Authorization evidence

The post-approval gate writes:

`release-authorization.json`

It records:

- repository;
- release tag;
- exact source SHA;
- resolved tag commit;
- release branch;
- branch-protection result;
- reachability result;
- workflow path, run ID, run number, run attempt, event, branch, SHA, status, and conclusion for every required production workflow.

The file is:

1. attested;
2. uploaded to the draft release;
3. included in final SHA256 checksums;
4. verified after publication.

## Exact attestation verification

Published file and container attestations must verify against:

```
--repo "$GITHUB_REPOSITORY"
--source-digest "$GITHUB_SHA"
--source-ref "$GITHUB_REF"
--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"
```

Repository identity by itself is not accepted as the entire release provenance policy.

## Threats covered

PR-20 denies:

- a tag created from an unmerged feature commit;
- a tag moved after the triggering event;
- release from an unprotected `main`;
- reusing green CI from another SHA;
- accepting PR-only verification in place of a main push verification;
- accepting a failed/in-progress required workflow;
- accepting a similarly named workflow at another path;
- publishing after authorization if tag/branch state changed during environment approval;
- post-publication attestation verification that only checks repository identity while ignoring exact source revision.

## Scope boundary

PR-20 verifies whether GitHub reports the release branch as protected. It does not grant the workflow GitHub Administration permission to introspect or modify every branch/ruleset parameter.

Repository administrators must still configure the intended `main` and `v*` protections described in `docs/source-release-governance.md`.

This is deliberate least privilege: publishing code should not receive repository-administration authority merely to prove that an external administrative control exists.
