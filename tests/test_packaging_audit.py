from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_modern_pep639_metadata_and_dev_tools_are_declared(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires = ["setuptools>=77"]', pyproject)
        self.assertIn('license = "MIT"', pyproject)
        self.assertIn('license-files = ["LICENSE*"]', pyproject)
        self.assertIn("[project.urls]", pyproject)
        self.assertIn("[project.optional-dependencies]", pyproject)
        self.assertIn('"build>=1.3"', pyproject)
        self.assertIn('"ruff>=0.12"', pyproject)
        self.assertIn('"mypy>=1.17"', pyproject)
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('[tool.setuptools.dynamic]', pyproject)

    def test_cli_version_uses_same_source_as_package(self):
        from ai_workflow import __version__
        from ai_workflow._version import __version__ as source_version

        self.assertEqual(__version__, source_version)
        proc = subprocess.run(
            [sys.executable, "-m", "ai_workflow", "--version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), source_version)


class WorkflowSupplyChainTests(unittest.TestCase):
    def _workflow(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_ci_has_least_privilege_quality_package_and_macos_paths(self):
        ci = self._workflow("tests.yml")
        self.assertIn("permissions:\n  contents: read", ci)
        self.assertIn("macos", ci)
        self.assertRegex(ci, r"\bquality:")
        self.assertRegex(ci, r"\bpackage-smoke:")
        self.assertIn("pipx", ci)
        self.assertIn("uv", ci)

    def test_all_uses_references_in_repo_workflows_are_full_sha_pins(self):
        workflows = list((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertTrue(workflows)
        offenders = []
        for path in workflows:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.search(r"\buses:\s*[^@\s]+@([^\s#]+)", line)
                if match and not re.fullmatch(r"[0-9a-fA-F]{40}", match.group(1)):
                    offenders.append(f"{path.name}: {line.strip()}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
