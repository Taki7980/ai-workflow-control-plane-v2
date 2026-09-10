from __future__ import annotations

import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_modern_pep639_metadata_and_dev_tools_are_declared(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("setuptools>=77", data["build-system"]["requires"])
        project = data["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE*"])
        self.assertIn("urls", project)
        dev = project["optional-dependencies"]["dev"]
        self.assertTrue(any(x.startswith("build") for x in dev))
        self.assertTrue(any(x.startswith("ruff") for x in dev))
        self.assertTrue(any(x.startswith("mypy") for x in dev))
        self.assertIn("version", project.get("dynamic", []))

    def test_cli_version_uses_same_source_as_package(self):
        from ai_workflow import __version__
        from ai_workflow._version import __version__ as source_version

        self.assertEqual(__version__, source_version)
        proc = subprocess.run([sys.executable, "-m", "ai_workflow", "--version"], cwd=ROOT, text=True, capture_output=True)
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

    def test_release_uses_oidc_attestations_native_binaries_and_checksums(self):
        release = self._workflow("release.yml")
        self.assertIn("id-token: write", release)
        self.assertIn("attestations: write", release)
        self.assertIn("pypa/gh-action-pypi-publish", release)
        self.assertIn("pyinstaller", release.lower())
        self.assertIn("SHA256SUMS", release)
        self.assertIn("gh release", release)
        self.assertIn("sbom", release.lower())


class DistributionSurfaceTests(unittest.TestCase):
    def test_docker_is_non_root_and_contains_git_and_ripgrep(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?i)\bgit\b")
        self.assertRegex(dockerfile, r"(?i)\bripgrep\b")
        self.assertRegex(dockerfile, r"(?m)^USER\s+(?!root\b)\S+")
        self.assertTrue((ROOT / ".dockerignore").is_file())

    def test_release_installers_verify_sha256(self):
        posix = (ROOT / "install.sh").read_text(encoding="utf-8").lower()
        powershell = (ROOT / "install.ps1").read_text(encoding="utf-8").lower()
        self.assertIn("sha256", posix)
        self.assertIn("version", posix)
        self.assertIn("sha256", powershell)
        self.assertIn("version", powershell)

    def test_winget_homebrew_conda_and_renderer_exist(self):
        required = [
            "packaging/winget/manifest.yaml.in",
            "packaging/homebrew/ai-workflow.rb.in",
            "packaging/conda/meta.yaml.in",
            "scripts/render_distribution_manifests.py",
            "docs/distribution.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
        ]
        for rel in required:
            self.assertTrue((ROOT / rel).is_file(), rel)


if __name__ == "__main__":
    unittest.main()
