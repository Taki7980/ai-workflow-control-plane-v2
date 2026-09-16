from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DistributionContractTests(unittest.TestCase):
    def _text(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_supported_python_floor_is_311(self) -> None:
        pyproject = self._text("pyproject.toml")
        tests_workflow = self._text(".github/workflows/tests.yml")
        conda = self._text("packaging/conda/meta.yaml.in")

        self.assertIn('requires-python = ">=3.11"', pyproject)
        self.assertIn('python_version = "3.11"', pyproject)
        self.assertNotIn('python-version: "3.10"', tests_workflow)
        self.assertGreaterEqual(conda.count("python >=3.11"), 2)
        self.assertNotIn("python >=3.10", conda)

    def test_installers_default_to_latest_release_without_hardcoded_version(self) -> None:
        shell = self._text("install.sh")
        powershell = self._text("install.ps1")

        self.assertNotIn('AI_WORKFLOW_VERSION:-2.3.0', shell)
        self.assertNotIn('[string]$Version = "2.3.0"', powershell)

        self.assertIn("AI_WORKFLOW_VERSION", shell)
        self.assertIn("releases/latest", shell)

        self.assertIn("$Version", powershell)
        self.assertIn("releases/latest", powershell)

    def test_installers_emit_checksum_and_attestation_guidance(self) -> None:
        shell = self._text("install.sh")
        powershell = self._text("install.ps1")

        for source in (shell, powershell):
            self.assertIn("SHA-256 verified", source)
            self.assertIn("gh attestation verify", source)
            self.assertIn("Taki7980/ai-workflow-control-plane-v2", source)

    def test_pyinstaller_pin_matches_current_tested_release(self) -> None:
        release = self._text(".github/workflows/release.yml")
        tests = self._text(".github/workflows/tests.yml")

        self.assertIn('pyinstaller==6.22.3', release)
        self.assertIn('pyinstaller==6.22.3', tests)

    def test_pr_installation_smoke_covers_portable_docker_and_bootstrap(self) -> None:
        workflow = self._text(".github/workflows/tests.yml")

        self.assertIn("portable-binary-smoke:", workflow)
        self.assertIn("docker-install-smoke:", workflow)
        self.assertIn("bootstrap-installer-smoke:", workflow)
        self.assertIn("scripts/smoke_bootstrap_install.py", workflow)

    def test_release_pipeline_verifies_published_artifacts(self) -> None:
        workflow = self._text(".github/workflows/release.yml")

        self.assertIn("verify-release:", workflow)
        self.assertRegex(
            workflow,
            r"(?ms)^  verify-release:\n.*?needs: finalize-release",
        )
        self.assertIn("gh attestation verify", workflow)
        self.assertIn("sha256sum --check", workflow)
        self.assertIn("install.sh", workflow)

    def test_distribution_renderer_emits_fully_resolved_current_manifests(self) -> None:
        fake_hashes = {
            "ai-workflow-v9.8.7-windows-x86_64.exe": "1" * 64,
            "ai-workflow-v9.8.7-linux-x86_64": "2" * 64,
            "ai-workflow-v9.8.7-macos-arm64": "3" * 64,
            "ai-workflow-v9.8.7-macos-x86_64": "4" * 64,
            "ai_workflow_control_plane-9.8.7.tar.gz": "5" * 64,
        }

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            checksums = tmp / "SHA256SUMS"
            checksums.write_text(
                "".join(
                    f"{digest}  {name}\n"
                    for name, digest in fake_hashes.items()
                ),
                encoding="utf-8",
            )
            output = tmp / "out"

            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/render_distribution_manifests.py"),
                    "--version",
                    "9.8.7",
                    "--checksums",
                    str(checksums),
                    "--output-dir",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            expected = {
                "Taki7980.AIWorkflow.yaml",
                "Taki7980.AIWorkflow.installer.yaml",
                "Taki7980.AIWorkflow.locale.en-US.yaml",
                "ai-workflow.rb",
                "meta.yaml",
            }
            self.assertEqual(
                {p.name for p in output.iterdir()},
                expected,
            )

            rendered = {
                path.name: path.read_text(encoding="utf-8")
                for path in output.iterdir()
            }
            for name, text in rendered.items():
                with self.subTest(name=name):
                    self.assertNotIn("@", text)

            winget = rendered["Taki7980.AIWorkflow.installer.yaml"]
            self.assertIn("ManifestVersion: 1.12.0", winget)
            self.assertIn(fake_hashes["ai-workflow-v9.8.7-windows-x86_64.exe"], winget)

            brew = rendered["ai-workflow.rb"]
            self.assertIn(fake_hashes["ai-workflow-v9.8.7-linux-x86_64"], brew)
            self.assertIn(fake_hashes["ai-workflow-v9.8.7-macos-arm64"], brew)
            self.assertIn(fake_hashes["ai-workflow-v9.8.7-macos-x86_64"], brew)

            conda = rendered["meta.yaml"]
            self.assertIn(fake_hashes["ai_workflow_control_plane-9.8.7.tar.gz"], conda)
            self.assertGreaterEqual(conda.count("python >=3.11"), 2)
            self.assertNotIn("python >=3.10", conda)

    def test_distribution_docs_cover_install_upgrade_and_uninstall(self) -> None:
        docs = self._text("docs/distribution.md")
        readme = self._text("README.md")

        self.assertIn("uv tool install ai-workflow-control-plane", docs)
        self.assertIn("uv tool upgrade ai-workflow-control-plane", docs)
        self.assertIn("uv tool uninstall ai-workflow-control-plane", docs)
        self.assertIn("pipx install ai-workflow-control-plane", docs)
        self.assertIn("pipx upgrade ai-workflow-control-plane", docs)
        self.assertIn("pipx uninstall ai-workflow-control-plane", docs)
        self.assertIn("latest stable", docs.lower())
        self.assertIn("submission inputs", docs.lower())

        self.assertIn("Requires Python 3.11+", readme)
        self.assertIn("uv tool install ai-workflow-control-plane", readme)


if __name__ == "__main__":
    unittest.main()
