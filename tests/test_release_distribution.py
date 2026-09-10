from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseDistributionTests(unittest.TestCase):
    def test_tag_release_uses_oidc_attestation_and_native_binary_matrix(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn('tags:', workflow)
        self.assertIn('"v*"', workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("attestations: write", workflow)
        self.assertIn("pypa/gh-action-pypi-publish@", workflow)
        self.assertIn("pyinstaller", workflow.lower())
        self.assertIn("SHA256SUMS", workflow)
        self.assertIn("gh release", workflow)
        self.assertIn("--sbom=true", workflow)
        for label in ("ubuntu-latest", "windows-latest", "macos-latest", "macos-15-intel"):
            self.assertIn(label, workflow)

    def test_release_workflow_uses_are_immutable_sha_pins(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        offenders = []
        for line in workflow.splitlines():
            match = re.search(r"\buses:\s*[^@\s]+@([^\s#]+)", line)
            if match and not re.fullmatch(r"[0-9a-fA-F]{40}", match.group(1)):
                offenders.append(line.strip())
        self.assertEqual(offenders, [])

    def test_portable_distribution_files_exist_and_verify_checksums(self):
        required = [
            "Dockerfile",
            ".dockerignore",
            "packaging/entrypoint.py",
            "packaging/winget/manifest.yaml.in",
            "packaging/homebrew/ai-workflow.rb.in",
            "packaging/conda/meta.yaml.in",
            "scripts/render_distribution_manifests.py",
            "install.sh",
            "install.ps1",
            "docs/distribution.md",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)
        self.assertIn("sha256", (ROOT / "install.sh").read_text(encoding="utf-8").lower())
        self.assertIn("sha256", (ROOT / "install.ps1").read_text(encoding="utf-8").lower())

    def test_container_keeps_tooling_explicit_and_runtime_non_root(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("git", dockerfile)
        self.assertIn("ripgrep", dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER\s+(?!root\b)\S+")
        self.assertIn('ENTRYPOINT ["ai-workflow"]', dockerfile)


if __name__ == "__main__":
    unittest.main()
