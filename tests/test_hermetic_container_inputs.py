from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUTS = json.loads(
    (ROOT / "packaging" / "container" / "inputs.json").read_text(encoding="utf-8")
)


class HermeticContainerInputTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_all_external_docker_materials_are_digest_pinned(self) -> None:
        dockerfile = self._read("Dockerfile")
        frontend = INPUTS["dockerfile_frontend"]
        python_base = INPUTS["python_base"]
        uv_image = INPUTS["uv_image"]

        self.assertTrue(
            dockerfile.startswith(
                f"# syntax={frontend['ref']}@{frontend['index_digest']}"
            )
        )
        self.assertIn(
            f"FROM {uv_image['ref']}@{uv_image['index_digest']} AS uv",
            dockerfile,
        )
        python_from = (
            f"FROM {python_base['ref']}@{python_base['index_digest']}"
        )
        self.assertEqual(dockerfile.count(python_from), 2)

        for line in dockerfile.splitlines():
            if line.startswith("FROM "):
                image = line.split()[1]
                self.assertRegex(image, r"@sha256:[0-9a-f]{64}$")

    def test_runtime_apt_state_is_frozen_without_blanket_upgrade(self) -> None:
        dockerfile = self._read("Dockerfile")
        sources = self._read("packaging/container/debian.sources")
        packages = self._read("packaging/container/runtime-packages.txt")

        self.assertNotIn("apt-get upgrade", dockerfile)
        self.assertIn("apt-get update", dockerfile)
        self.assertIn("runtime-packages.txt", dockerfile)
        for ephemeral in (
            "/var/log/apt/*",
            "/var/log/dpkg.log",
            "/var/log/alternatives.log",
        ):
            self.assertIn(ephemeral, dockerfile)
        self.assertNotIn("deb.debian.org", sources)
        self.assertNotIn("security.debian.org", sources)
        self.assertEqual(
            sources.count(INPUTS["debian_snapshot"]),
            2,
        )
        self.assertEqual(sources.count("Check-Valid-Until: no"), 2)

        expected = {
            f"{name}={version}"
            for name, version in INPUTS["runtime_packages"].items()
        }
        actual = {
            line.strip()
            for line in packages.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(actual, expected)

    def test_uv_bootstrap_is_an_immutable_oci_material(self) -> None:
        dockerfile = self._read("Dockerfile")
        self.assertIn("COPY --from=uv /uv /usr/local/bin/uv", dockerfile)
        self.assertNotIn("pip install --no-cache-dir \"uv==", dockerfile)

    def test_container_workflows_pin_buildx_and_buildkit(self) -> None:
        builder = INPUTS["builder"]
        for relative in (
            ".github/workflows/tests.yml",
            ".github/workflows/security.yml",
            ".github/workflows/release.yml",
        ):
            with self.subTest(relative=relative):
                workflow = self._read(relative)
                self.assertIn(builder["setup_buildx_action"], workflow)
                self.assertIn(
                    f"version: {builder['buildx_version']}",
                    workflow,
                )
                self.assertIn(
                    (
                        f"image={builder['buildkit_ref']}@"
                        f"{builder['buildkit_index_digest']}"
                    ),
                    workflow,
                )
                self.assertIn("SOURCE_DATE_EPOCH", workflow)
                self.assertIn("--build-arg SOURCE_DATE_EPOCH", workflow)
                self.assertIn("rewrite-timestamp=true", workflow)

        for relative in (
            ".github/workflows/tests.yml",
            ".github/workflows/release.yml",
        ):
            with self.subTest(deterministic_image_export=relative):
                workflow = self._read(relative)
                self.assertIn(
                    "--build-arg BUILDKIT_MULTI_PLATFORM=1",
                    workflow,
                )

    def test_ci_rebuilds_twice_and_compares_release_image_digest(self) -> None:
        workflow = self._read(".github/workflows/tests.yml")
        self.assertIn("ai-workflow-repro-a", workflow)
        self.assertIn("ai-workflow-repro-b", workflow)
        self.assertGreaterEqual(workflow.count("--no-cache"), 2)
        self.assertGreaterEqual(workflow.count("type=image"), 2)
        self.assertGreaterEqual(
            workflow.count("compatibility-version=30"),
            2,
        )
        self.assertGreaterEqual(workflow.count("--provenance=false"), 2)
        self.assertIn('."containerimage.digest"', workflow)
        self.assertIn('test "$first" = "$second"', workflow)
        self.assertIn("Smoke Docker-loaded image separately", workflow)

    def test_release_exports_and_validates_slsa_v1_and_spdx(self) -> None:
        workflow = self._read(".github/workflows/release.yml")
        self.assertIn("--provenance=mode=max,version=v1", workflow)
        self.assertIn("--sbom=true", workflow)
        self.assertIn("compatibility-version=30", workflow)
        self.assertIn(".Provenance.SLSA", workflow)
        self.assertIn(".SBOM.SPDX", workflow)
        self.assertIn("verify_container_attestations.py", workflow)
        self.assertIn("container-provenance.json", workflow)
        self.assertIn("container-sbom.spdx.json", workflow)

    def test_container_lock_authority_is_owned(self) -> None:
        owners = self._read(".github/CODEOWNERS")
        for path in (
            "/Dockerfile @Taki7980",
            "/packaging/container/ @Taki7980",
            "/scripts/verify_container_attestations.py @Taki7980",
            "/.github/dependabot.yml @Taki7980",
        ):
            self.assertIn(path, owners)

    def test_docker_digest_updates_are_surfaced_for_review(self) -> None:
        dependabot = self._read(".github/dependabot.yml")
        self.assertIn("package-ecosystem: docker", dependabot)
        self.assertIn("interval: weekly", dependabot)

    def test_one_time_discovery_workflow_is_removed(self) -> None:
        self.assertFalse(
            (ROOT / ".github" / "workflows" / "pr19-discovery.yml").exists()
        )


if __name__ == "__main__":
    unittest.main()
