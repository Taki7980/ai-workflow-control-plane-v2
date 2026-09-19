from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REQUIRED_WORKFLOWS = (
    ".github/workflows/tests.yml",
    ".github/workflows/security.yml",
    ".github/workflows/codeql.yml",
)
API_VERSION = "2026-03-10"


class ReleaseAuthorizationError(RuntimeError):
    pass


def _run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise ReleaseAuthorizationError(
            f"git {' '.join(args)} failed: {detail}"
        )
    return proc.stdout.strip()


def resolve_remote_release_state(tag: str, release_branch: str) -> tuple[str, bool]:
    _run_git(
        "fetch",
        "--force",
        "--no-tags",
        "origin",
        f"+refs/heads/{release_branch}:refs/remotes/origin/{release_branch}",
    )
    _run_git(
        "fetch",
        "--force",
        "origin",
        f"+refs/tags/{tag}:refs/tags/{tag}",
    )
    tag_commit = _run_git("rev-parse", f"refs/tags/{tag}^{{commit}}")
    proc = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            tag_commit,
            f"refs/remotes/origin/{release_branch}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise ReleaseAuthorizationError(
            "git merge-base --is-ancestor failed: "
            + proc.stderr.strip()
        )
    return tag_commit, proc.returncode == 0


def _api_get_json(
    *,
    api_url: str,
    repository: str,
    path: str,
    token: str,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    base = api_url.rstrip("/")
    url = f"{base}/repos/{repository}/{path.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ai-workflow-release-authorization",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ReleaseAuthorizationError(
            f"GitHub API request failed ({exc.code}) for {path}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ReleaseAuthorizationError(
            f"GitHub API request failed for {path}: {exc}"
        ) from exc
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ReleaseAuthorizationError(
            f"GitHub API returned non-object JSON for {path}"
        )
    return data


def select_successful_workflow_run(
    *,
    workflow_path: str,
    release_branch: str,
    expected_sha: str,
    runs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    matches = [
        run
        for run in runs
        if run.get("path") == workflow_path
        and run.get("event") == "push"
        and run.get("head_branch") == release_branch
        and run.get("head_sha") == expected_sha
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    if not matches:
        raise ReleaseAuthorizationError(
            "required workflow has no successful main-push run for exact SHA: "
            f"{workflow_path} @ {expected_sha}"
        )
    return max(
        matches,
        key=lambda run: (
            int(run.get("run_attempt") or 0),
            int(run.get("run_number") or 0),
            int(run.get("id") or 0),
        ),
    )


def evaluate_release_authorization(
    *,
    expected_sha: str,
    tag_commit: str,
    release_branch: str,
    branch_protected: bool,
    tag_is_ancestor: bool,
    required_workflows: Iterable[str],
    workflow_runs: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    if not SHA_RE.fullmatch(expected_sha):
        raise ReleaseAuthorizationError(
            f"invalid expected release SHA: {expected_sha!r}"
        )
    if tag_commit != expected_sha:
        raise ReleaseAuthorizationError(
            "tag does not resolve to the workflow event SHA: "
            f"tag={tag_commit} event={expected_sha}"
        )
    if not branch_protected:
        raise ReleaseAuthorizationError(
            f"release branch {release_branch!r} is not protected"
        )
    if not tag_is_ancestor:
        raise ReleaseAuthorizationError(
            f"release SHA {expected_sha} is not reachable from "
            f"{release_branch!r}"
        )

    verified_runs: list[dict[str, Any]] = []
    for workflow_path in required_workflows:
        run = select_successful_workflow_run(
            workflow_path=workflow_path,
            release_branch=release_branch,
            expected_sha=expected_sha,
            runs=workflow_runs.get(workflow_path, []),
        )
        verified_runs.append(
            {
                "workflow_path": workflow_path,
                "run_id": run.get("id"),
                "run_number": run.get("run_number"),
                "run_attempt": run.get("run_attempt"),
                "event": run.get("event"),
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
            }
        )

    return {
        "schema_version": 1,
        "authorized": True,
        "repository_sha": expected_sha,
        "tag_commit": tag_commit,
        "release_branch": release_branch,
        "release_branch_protected": True,
        "tag_reachable_from_release_branch": True,
        "required_workflows": verified_runs,
    }


def verify_release_authorization(
    *,
    repository: str,
    expected_sha: str,
    tag: str,
    release_branch: str,
    token: str,
    api_url: str,
    required_workflows: Iterable[str],
) -> dict[str, Any]:
    if "/" not in repository:
        raise ReleaseAuthorizationError(
            f"repository must be owner/name, got {repository!r}"
        )

    tag_commit, tag_is_ancestor = resolve_remote_release_state(
        tag,
        release_branch,
    )

    branch = _api_get_json(
        api_url=api_url,
        repository=repository,
        path=f"branches/{urllib.parse.quote(release_branch, safe='')}",
        token=token,
    )
    branch_protected = branch.get("protected") is True

    workflow_runs: dict[str, list[dict[str, Any]]] = {}
    for workflow_path in required_workflows:
        workflow_id = Path(workflow_path).name
        data = _api_get_json(
            api_url=api_url,
            repository=repository,
            path=(
                "actions/workflows/"
                + urllib.parse.quote(workflow_id, safe="")
                + "/runs"
            ),
            token=token,
            query={
                "branch": release_branch,
                "event": "push",
                "head_sha": expected_sha,
                "per_page": "100",
            },
        )
        runs = data.get("workflow_runs")
        if not isinstance(runs, list):
            raise ReleaseAuthorizationError(
                f"workflow-runs response missing list for {workflow_path}"
            )
        workflow_runs[workflow_path] = [
            run for run in runs if isinstance(run, dict)
        ]

    evidence = evaluate_release_authorization(
        expected_sha=expected_sha,
        tag_commit=tag_commit,
        release_branch=release_branch,
        branch_protected=branch_protected,
        tag_is_ancestor=tag_is_ancestor,
        required_workflows=required_workflows,
        workflow_runs=workflow_runs,
    )
    evidence["repository"] = repository
    evidence["tag"] = tag
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed unless a release tag resolves to an exact, protected, "
            "main-reachable SHA whose required production workflows succeeded."
        )
    )
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--release-branch", default="main")
    parser.add_argument(
        "--required-workflow",
        action="append",
        dest="required_workflows",
        default=None,
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("repository", args.repository),
            ("sha", args.sha),
            ("tag", args.tag),
            ("token", args.token),
        )
        if not value
    ]
    if missing:
        parser.error("missing required values: " + ", ".join(missing))

    required_workflows = tuple(
        args.required_workflows or DEFAULT_REQUIRED_WORKFLOWS
    )

    try:
        evidence = verify_release_authorization(
            repository=str(args.repository),
            expected_sha=str(args.sha),
            tag=str(args.tag),
            release_branch=args.release_branch,
            token=str(args.token),
            api_url=args.api_url,
            required_workflows=required_workflows,
        )
    except ReleaseAuthorizationError as exc:
        print(f"release authorization denied: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
