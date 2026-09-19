from __future__ import annotations

import unittest

from scripts.verify_release_authorization import (
    ReleaseAuthorizationError,
    _api_get_json,
    evaluate_release_authorization,
    select_successful_workflow_run,
)


SHA = "a" * 40
OTHER_SHA = "b" * 40
BRANCH = "main"
WORKFLOWS = (
    ".github/workflows/tests.yml",
    ".github/workflows/security.yml",
    ".github/workflows/codeql.yml",
)


def _run(
    workflow_path: str,
    *,
    run_id: int = 1,
    sha: str = SHA,
    branch: str = BRANCH,
    event: str = "push",
    status: str = "completed",
    conclusion: str = "success",
) -> dict[str, object]:
    return {
        "id": run_id,
        "run_number": run_id,
        "run_attempt": 1,
        "path": workflow_path,
        "event": event,
        "head_branch": branch,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://example.invalid/runs/{run_id}",
    }


def _runs() -> dict[str, list[dict[str, object]]]:
    return {
        workflow: [_run(workflow, run_id=index)]
        for index, workflow in enumerate(WORKFLOWS, start=1)
    }


class ReleaseAuthorizationTests(unittest.TestCase):
    def test_accepts_exact_sha_on_protected_release_branch_with_green_push_runs(
        self,
    ) -> None:
        evidence = evaluate_release_authorization(
            expected_sha=SHA,
            tag_commit=SHA,
            release_branch=BRANCH,
            branch_protected=True,
            tag_is_ancestor=True,
            required_workflows=WORKFLOWS,
            workflow_runs=_runs(),
        )

        self.assertTrue(evidence["authorized"])
        self.assertEqual(evidence["repository_sha"], SHA)
        self.assertEqual(evidence["tag_commit"], SHA)
        self.assertTrue(evidence["release_branch_protected"])
        self.assertEqual(
            [item["workflow_path"] for item in evidence["required_workflows"]],
            list(WORKFLOWS),
        )

    def test_rejects_unprotected_release_branch(self) -> None:
        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "is not protected",
        ):
            evaluate_release_authorization(
                expected_sha=SHA,
                tag_commit=SHA,
                release_branch=BRANCH,
                branch_protected=False,
                tag_is_ancestor=True,
                required_workflows=WORKFLOWS,
                workflow_runs=_runs(),
            )

    def test_rejects_tag_that_moved_away_from_event_sha(self) -> None:
        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "tag does not resolve",
        ):
            evaluate_release_authorization(
                expected_sha=SHA,
                tag_commit=OTHER_SHA,
                release_branch=BRANCH,
                branch_protected=True,
                tag_is_ancestor=True,
                required_workflows=WORKFLOWS,
                workflow_runs=_runs(),
            )

    def test_rejects_sha_not_reachable_from_release_branch(self) -> None:
        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "not reachable",
        ):
            evaluate_release_authorization(
                expected_sha=SHA,
                tag_commit=SHA,
                release_branch=BRANCH,
                branch_protected=True,
                tag_is_ancestor=False,
                required_workflows=WORKFLOWS,
                workflow_runs=_runs(),
            )

    def test_rejects_required_workflow_without_exact_sha_success(self) -> None:
        runs = _runs()
        runs[WORKFLOWS[0]] = [
            _run(WORKFLOWS[0], sha=OTHER_SHA),
            _run(WORKFLOWS[0], event="pull_request"),
            _run(WORKFLOWS[0], conclusion="failure"),
        ]

        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "no successful main-push run for exact SHA",
        ):
            evaluate_release_authorization(
                expected_sha=SHA,
                tag_commit=SHA,
                release_branch=BRANCH,
                branch_protected=True,
                tag_is_ancestor=True,
                required_workflows=WORKFLOWS,
                workflow_runs=runs,
            )

    def test_selects_latest_valid_attempt_without_accepting_wrong_context(self) -> None:
        workflow = WORKFLOWS[0]
        selected = select_successful_workflow_run(
            workflow_path=workflow,
            release_branch=BRANCH,
            expected_sha=SHA,
            runs=[
                _run(workflow, run_id=1, event="pull_request"),
                _run(workflow, run_id=2, sha=OTHER_SHA),
                {
                    **_run(workflow, run_id=3),
                    "run_attempt": 1,
                    "run_number": 10,
                },
                {
                    **_run(workflow, run_id=4),
                    "run_attempt": 2,
                    "run_number": 10,
                },
            ],
        )
        self.assertEqual(selected["id"], 4)

    def test_rejects_non_https_api_base_before_network_access(self) -> None:
        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "must be an absolute HTTPS URL",
        ):
            _api_get_json(
                api_url="http://api.github.com",
                repository="owner/repo",
                path="branches/main",
                token="not-a-real-token",
            )

    def test_rejects_invalid_release_sha_shape(self) -> None:
        with self.assertRaisesRegex(
            ReleaseAuthorizationError,
            "invalid expected release SHA",
        ):
            evaluate_release_authorization(
                expected_sha="main",
                tag_commit="main",
                release_branch=BRANCH,
                branch_protected=True,
                tag_is_ancestor=True,
                required_workflows=WORKFLOWS,
                workflow_runs=_runs(),
            )


if __name__ == "__main__":
    unittest.main()
