from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.verify_container_attestations import verify_provenance, verify_sbom


ROOT = Path(__file__).resolve().parents[1]
INPUTS = json.loads(
    (ROOT / "packaging" / "container" / "inputs.json").read_text(encoding="utf-8")
)


class ContainerAttestationVerifierTests(unittest.TestCase):
    def test_accepts_locked_materials_and_runtime_packages(self) -> None:
        provenance = {
            "buildDefinition": {
                "resolvedDependencies": [
                    {
                        "uri": INPUTS["python_base"]["ref"],
                        "digest": {
                            "sha256": INPUTS["python_base"][
                                "linux_amd64_digest"
                            ].split(":", 1)[1]
                        },
                    },
                    {
                        "uri": INPUTS["uv_image"]["ref"],
                        "digest": {
                            "sha256": INPUTS["uv_image"][
                                "linux_amd64_digest"
                            ].split(":", 1)[1]
                        },
                    },
                ]
            }
        }
        sbom = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [
                {
                    "name": name,
                    "versionInfo": version,
                }
                for name, version in INPUTS["runtime_packages"].items()
            ],
        }

        verify_provenance(provenance, INPUTS)
        verify_sbom(sbom, INPUTS)

    def test_rejects_missing_base_material(self) -> None:
        provenance = {
            "buildDefinition": {
                "resolvedDependencies": [
                    {
                        "uri": INPUTS["uv_image"]["ref"],
                        "digest": {
                            "sha256": INPUTS["uv_image"][
                                "linux_amd64_digest"
                            ].split(":", 1)[1]
                        },
                    }
                ]
            }
        }
        with self.assertRaisesRegex(ValueError, "python_base"):
            verify_provenance(provenance, INPUTS)

    def test_rejects_sbom_without_locked_package_version(self) -> None:
        sbom = {
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [
                {"name": "git", "versionInfo": "unexpected"},
                {
                    "name": "ripgrep",
                    "versionInfo": INPUTS["runtime_packages"]["ripgrep"],
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "locked git version"):
            verify_sbom(sbom, INPUTS)


if __name__ == "__main__":
    unittest.main()
