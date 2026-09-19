from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_UV_SHA = "c771a70e6277c0a99b617c7a806ffedaca235ff9"
UV_VERSION = "0.12.14"


class HermeticPythonInputTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_direct_python_tool_inputs_are_exactly_pinned(self) -> None:
        data = tomllib.loads(self._read("pyproject.toml"))
        self.assertEqual(
            data["build-system"]["requires"],
            ["setuptools==84.0.0"],
        )
        groups = data["dependency-groups"]
        required_groups = {
            "build",
            "dev",
            "security",
            "crg",
            "portable",
            "package-smoke",
        }
        self.assertTrue(required_groups.issubset(groups))
        for group in sorted(required_groups):
            with self.subTest(group=group):
                requirements = groups[group]
                self.assertTrue(requirements)
                for requirement in requirements:
                    self.assertIsInstance(requirement, str)
                    self.assertRegex(
                        requirement,
                        r"^[A-Za-z0-9_.-]+==[^=<>!~]+$",
                    )

    def test_uv_lock_is_universal_and_registry_artifacts_are_hashed(self) -> None:
        lock = tomllib.loads(self._read("uv.lock"))
        self.assertEqual(lock["version"], 1)
        self.assertEqual(lock["requires-python"], ">=3.11")
        self.assertTrue(lock.get("resolution-markers"))

        registry_packages = 0
        for package in lock["package"]:
            source = package.get("source", {})
            if "registry" not in source:
                continue
            registry_packages += 1
            self.assertTrue(package.get("version"), package["name"])
            artifacts = []
            sdist = package.get("sdist")
            if sdist is not None:
                artifacts.append(sdist)
            artifacts.extend(package.get("wheels", []))
            self.assertTrue(artifacts, package["name"])
            for artifact in artifacts:
                self.assertRegex(
                    artifact.get("hash", ""),
                    r"^sha256:[0-9a-f]{64}$",
                    package["name"],
                )
        self.assertGreater(registry_packages, 0)

    def test_ci_and_release_use_pinned_uv_and_locked_sync(self) -> None:
        for relative in (
            ".github/workflows/tests.yml",
            ".github/workflows/security.yml",
            ".github/workflows/release.yml",
        ):
            with self.subTest(relative=relative):
                workflow = self._read(relative)
                self.assertIn(f"astral-sh/setup-uv@{SETUP_UV_SHA}", workflow)
                self.assertIn(f'version: "{UV_VERSION}"', workflow)
                self.assertIn("--locked", workflow)
                self.assertNotIn("pip install --upgrade build", workflow)
                self.assertNotIn('pip install "pyinstaller==', workflow)
                self.assertNotIn('pip install "code-review-graph==', workflow)
                self.assertNotIn("security/requirements.txt", workflow)

        self.assertIn(
            "uv lock --check",
            self._read(".github/workflows/tests.yml"),
        )
        self.assertIn(
            "uv lock --check",
            self._read(".github/workflows/release.yml"),
        )

    def test_build_jobs_use_exact_interpreter_patches(self) -> None:
        tests = self._read(".github/workflows/tests.yml")
        for version in ("3.11.16", "3.12.14", "3.13.15", "3.14.7"):
            self.assertIn(f'python-version: "{version}"', tests)

        release = self._read(".github/workflows/release.yml")
        self.assertNotIn('python-version: "3.14"', release)
        self.assertIn('python-version: "3.14.7"', release)

    def test_build_frontend_uses_prelocked_backend_without_second_resolution(self) -> None:
        tests = self._read(".github/workflows/tests.yml")
        release = self._read(".github/workflows/release.yml")
        dockerfile = self._read("Dockerfile")

        for content in (tests, release):
            self.assertIn("python -m build --no-isolation", content)

        self.assertIn("COPY pyproject.toml uv.lock", dockerfile)
        self.assertIn('"uv==0.12.14"', dockerfile)
        self.assertIn("uv sync --locked --only-group build", dockerfile)
        self.assertIn("python -m build --wheel --no-isolation", dockerfile)
        self.assertNotIn("pip install --no-cache-dir build", dockerfile)

    def test_toolchain_identity_is_recorded_and_lock_is_owned(self) -> None:
        recorder = ROOT / "scripts" / "record_python_toolchain.py"
        self.assertTrue(recorder.is_file())
        raw = recorder.read_text(encoding="utf-8")
        self.assertIn("uv_lock_sha256", raw)
        self.assertIn("pyproject_toml_sha256", raw)
        self.assertIn('"packages"', raw)

        release = self._read(".github/workflows/release.yml")
        self.assertIn("python-build-toolchain.json", release)
        self.assertIn(".toolchain.json", release)

        owners = self._read(".github/CODEOWNERS")
        self.assertIn("/uv.lock @Taki7980", owners)
        self.assertIn(
            "/scripts/record_python_toolchain.py @Taki7980",
            owners,
        )

    def test_one_time_lock_generator_is_not_part_of_final_repository(self) -> None:
        self.assertFalse(
            (ROOT / ".github" / "workflows" / "pr18-lockgen.yml").exists()
        )


if __name__ == "__main__":
    unittest.main()
