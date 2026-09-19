from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _job_block(workflow: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"release workflow job missing: {job}")
    return match.group("body")


class SourceReleaseGovernanceTests(unittest.TestCase):
    def test_sensitive_paths_are_owned(self) -> None:
        raw = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        entries: dict[str, set[str]] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            pattern, *owners = stripped.split()
            entries[pattern] = set(owners)

        required = {
            "/.github/CODEOWNERS",
            "/.github/workflows/",
            "/SECURITY.md",
            "/pyproject.toml",
            "/uv.lock",
            "/scripts/record_python_toolchain.py",
            "/ai_workflow/crg_semantic_benchmark.py",
            "/scripts/run_crg_semantic_benchmark.py",
            "/scripts/check_crg_semantic_regression.py",
            "/benchmarks/crg-semantic-v1/",
            "/scripts/verify_release_authorization.py",
            "/Dockerfile",
            "/packaging/container/",
            "/scripts/verify_container_attestations.py",
            "/.github/dependabot.yml",
            "/install.sh",
            "/install.ps1",
            "/ai_workflow/provider_registry.py",
            "/ai_workflow/provider_runner.py",
            "/ai_workflow/telemetry.py",
            "/ai_workflow/deployment_*.py",
            "/ai_workflow/policy_manifest.py",
            "/ai_workflow/retrieval_learning.py",
            "/ai_workflow/outcome_verification.py",
            "/ai_workflow/provenance.py",
        }
        for pattern in required:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, entries)
                self.assertIn("@Taki7980", entries[pattern])

    def test_release_trigger_is_version_tags_only(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(workflow, r'(?ms)^  push:\n    tags:\n      - "v\*"')
        self.assertNotRegex(workflow, r"(?m)^    branches:")

    def test_release_starts_behind_protected_environment_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        prepare = _job_block(workflow, "prepare-release")
        pypi = _job_block(workflow, "publish-pypi")
        portable = _job_block(workflow, "portable-binaries")
        container = _job_block(workflow, "container")
        finalize = _job_block(workflow, "finalize-release")

        self.assertRegex(prepare, r"(?m)^    environment: release$")
        self.assertRegex(pypi, r"(?m)^    environment: pypi$")
        self.assertRegex(pypi, r"(?m)^    needs: prepare-release$")
        self.assertRegex(portable, r"(?m)^    needs: prepare-release$")
        self.assertRegex(container, r"(?m)^    needs: prepare-release$")
        self.assertRegex(
            finalize,
            r"(?m)^    needs: \[publish-pypi, portable-binaries, container\]$",
        )

    def test_release_requires_exact_sha_authorization_before_publish(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        authorize = _job_block(workflow, "authorize-release")
        prepare = _job_block(workflow, "prepare-release")
        verify = _job_block(workflow, "verify-release")

        self.assertRegex(authorize, r"(?m)^      actions: read$")
        self.assertRegex(authorize, r"(?m)^      contents: read$")
        self.assertIn("fetch-depth: 0", authorize)
        self.assertIn("verify_release_authorization.py", authorize)
        self.assertIn("--release-branch main", authorize)

        self.assertRegex(prepare, r"(?m)^    needs: authorize-release$")
        self.assertRegex(prepare, r"(?m)^    environment: release$")
        self.assertIn("verify_release_authorization.py", prepare)
        self.assertIn("release-authorization.json", prepare)
        self.assertIn("Attest release authorization evidence", prepare)

        self.assertIn("--source-digest \"$GITHUB_SHA\"", verify)
        self.assertIn("--source-ref \"$GITHUB_REF\"", verify)
        self.assertIn(
            '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"',
            verify,
        )
        self.assertIn("release-authorization.json", verify)

    def test_release_authorization_script_is_owned(self) -> None:
        raw = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertIn(
            "/scripts/verify_release_authorization.py @Taki7980",
            raw,
        )



if __name__ == "__main__":
    unittest.main()
