from __future__ import annotations

import copy
import unittest
from pathlib import Path

from ai_workflow.capability_evidence import load_manifest, validate_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "capabilities.json"


class CapabilityEvidenceManifestTests(unittest.TestCase):
    def _document(self):
        return load_manifest(MANIFEST)

    def test_checked_in_manifest_is_valid(self) -> None:
        summary = validate_manifest(self._document(), root=ROOT)

        self.assertGreaterEqual(summary["capabilities"], 10)
        self.assertGreater(summary["checked_paths"], summary["capabilities"])
        self.assertGreaterEqual(summary["research_sources"], 3)

    def test_missing_evidence_path_fails_closed(self) -> None:
        document = copy.deepcopy(self._document())
        document["capabilities"][0]["implementation"] = [
            "ai_workflow/does_not_exist.py"
        ]

        with self.assertRaisesRegex(ValueError, "does not exist"):
            validate_manifest(document, root=ROOT)

    def test_experimental_capability_cannot_be_production_default(self) -> None:
        document = copy.deepcopy(self._document())
        experimental = next(
            item
            for item in document["capabilities"]
            if item["status"] == "experimental"
        )
        experimental["production_default"] = True

        with self.assertRaisesRegex(
            ValueError,
            "cannot be production-default",
        ):
            validate_manifest(document, root=ROOT)

    def test_measured_claim_requires_benchmark_evidence(self) -> None:
        document = copy.deepcopy(self._document())
        measured = next(
            item
            for item in document["capabilities"]
            if item["evidence_level"] == "measured"
        )
        measured["benchmarks"] = []

        with self.assertRaisesRegex(
            ValueError,
            "measured evidence requires benchmark",
        ):
            validate_manifest(document, root=ROOT)

    def test_unknown_research_reference_is_rejected(self) -> None:
        document = copy.deepcopy(self._document())
        document["capabilities"][0]["research_refs"] = ["unknown-paper"]

        with self.assertRaisesRegex(
            ValueError,
            "unknown research source",
        ):
            validate_manifest(document, root=ROOT)


if __name__ == "__main__":
    unittest.main()
