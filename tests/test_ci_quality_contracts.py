from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEQL_SHA = "faaca9a8f6edddba5725ffe5adefdab6669a2eca"


class CIQualityContractTests(unittest.TestCase):
    def _text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_quality_workflow_uses_whole_repository_ruff(self) -> None:
        workflow = self._text(".github/workflows/tests.yml")
        pyproject = self._text("pyproject.toml")

        self.assertIn(
            "ruff check ai_workflow tests security_tests scripts",
            workflow,
        )
        self.assertNotIn("Ruff focused quality gate", workflow)
        self.assertIn("[tool.ruff.lint]", pyproject)
        self.assertIn('select = ["E9", "F", "B", "BLE", "EXE"]', pyproject)
        self.assertNotIn('select = ["ALL"]', pyproject)

    def test_quality_workflow_type_checks_entire_package(self) -> None:
        workflow = self._text(".github/workflows/tests.yml")

        self.assertIn("uv run --locked --no-sync mypy ai_workflow", workflow)
        self.assertNotIn("Mypy typed-boundary gate", workflow)
        self.assertNotIn("--follow-imports=skip", workflow)

    def test_security_workflow_requires_branch_aware_80_percent_coverage(self) -> None:
        workflow = self._text(".github/workflows/security.yml")

        self.assertIn(
            "coverage run --branch --source=ai_workflow -m unittest discover -s tests -q",
            workflow,
        )
        self.assertIn(
            "coverage report --fail-under=80 --show-missing",
            workflow,
        )
        self.assertNotIn("--fail-under=65", workflow)

    def test_codeql_workflow_is_pinned_and_least_privilege(self) -> None:
        workflow_path = ROOT / ".github/workflows/codeql.yml"
        self.assertTrue(workflow_path.is_file(), "CodeQL workflow must exist")
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertIn("security-events: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertGreaterEqual(workflow.count(CODEQL_SHA), 2)
        self.assertIn("github/codeql-action/init@", workflow)
        self.assertIn("github/codeql-action/analyze@", workflow)
        self.assertIn("languages: python", workflow)

    def test_container_policy_blocks_high_and_critical_with_explicit_exceptions(self) -> None:
        workflow = self._text(".github/workflows/security.yml")
        ignore_path = ROOT / "security/trivy-ignore.yaml"

        self.assertTrue(ignore_path.is_file(), "Trivy exception policy must exist")
        self.assertIn("--severity HIGH,CRITICAL", workflow)
        self.assertIn("--ignorefile security/trivy-ignore.yaml", workflow)
        self.assertNotIn("--severity CRITICAL\n", workflow)

        policy = ignore_path.read_text(encoding="utf-8")
        self.assertIn("vulnerabilities:", policy)
        self.assertIn("expired_at", policy)
        self.assertIn("statement", policy)


if __name__ == "__main__":
    unittest.main()
