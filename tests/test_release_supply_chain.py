from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _job_block(workflow: str, job: str) -> str:
    marker = f"  {job}:\n"
    start = workflow.find(marker)
    if start < 0:
        raise AssertionError(f"missing workflow job: {job}")
    match = re.search(r"^  [A-Za-z0-9_-]+:\s*$", workflow[start + len(marker):], re.M)
    if match is None:
        return workflow[start:]
    return workflow[start : start + len(marker) + match.start()]


class ReleaseSupplyChainTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_external_actions_are_full_commit_sha_pinned(self) -> None:
        action_pattern = re.compile(r"^\s*-\s+uses:\s+([^\s#]+)", re.M)
        sha_pattern = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
        checked = 0

        for path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
            workflow = path.read_text(encoding="utf-8")
            for reference in action_pattern.findall(workflow):
                if reference.startswith("./"):
                    continue
                checked += 1
                self.assertRegex(
                    reference,
                    sha_pattern,
                    f"{path.relative_to(ROOT)} uses mutable action reference {reference}",
                )

        self.assertGreater(checked, 0)

    def test_dependabot_tracks_github_actions(self) -> None:
        dependabot = self._read(".github/dependabot.yml")
        self.assertIn("package-ecosystem: github-actions", dependabot)
        self.assertIn("directory: /", dependabot)
        self.assertGreaterEqual(dependabot.count("interval: weekly"), 2)

    def test_ci_measures_python_distribution_reproducibility(self) -> None:
        workflow = self._read(".github/workflows/tests.yml")
        package_job = _job_block(workflow, "package-smoke")

        self.assertIn("SOURCE_DATE_EPOCH", package_job)
        self.assertGreaterEqual(package_job.count("git archive --format=tar HEAD"), 2)
        self.assertGreaterEqual(package_job.count("python -m build"), 2)
        self.assertIn("normalize_python_sdist.py", package_job)
        self.assertIn("verify_python_reproducibility.py", package_job)
        self.assertIn("python-reproducibility.json", package_job)

    def test_release_build_is_separate_from_pypi_oidc_publish(self) -> None:
        workflow = self._read(".github/workflows/release.yml")
        build_job = _job_block(workflow, "build-python-distributions")
        publish_job = _job_block(workflow, "publish-pypi")

        self.assertIn("needs: prepare-release", build_job)
        self.assertNotIn("environment: pypi", build_job)
        self.assertIn("SOURCE_DATE_EPOCH", build_job)
        self.assertGreaterEqual(build_job.count("git archive --format=tar HEAD"), 2)
        self.assertGreaterEqual(build_job.count("python -m build"), 2)
        self.assertIn("normalize_python_sdist.py", build_job)
        self.assertIn("verify_python_reproducibility.py", build_job)
        self.assertIn("python-reproducibility.json", build_job)
        self.assertIn("actions/attest@", build_job)

        self.assertIn("needs: build-python-distributions", publish_job)
        self.assertIn("environment: pypi", publish_job)
        self.assertIn("id-token: write", publish_job)
        self.assertIn("attestations: read", publish_job)
        self.assertIn("gh release download", publish_job)
        self.assertIn("gh attestation verify", publish_job)
        self.assertIn("pypa/gh-action-pypi-publish@", publish_job)

        for forbidden in (
            "actions/checkout@",
            "actions/setup-python@",
            "astral-sh/setup-uv@",
            "python -m build",
            "actions/attest@",
            "contents: write",
            "attestations: write",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, publish_job)

    def test_reproducibility_verifier_is_codeowned(self) -> None:
        owners = self._read(".github/CODEOWNERS")
        self.assertIn(
            "/scripts/verify_python_reproducibility.py @Taki7980",
            owners,
        )
        self.assertIn(
            "/scripts/normalize_python_sdist.py @Taki7980",
            owners,
        )


if __name__ == "__main__":
    unittest.main()
