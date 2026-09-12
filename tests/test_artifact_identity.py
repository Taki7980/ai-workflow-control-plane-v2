from __future__ import annotations

import unittest


class ArtifactIdentityTests(unittest.TestCase):
    def test_security_sensitive_artifacts_require_sha256_digest(self) -> None:
        from ai_workflow.provenance import ArtifactReference

        for kind in (
            "model",
            "dataset",
            "policy",
            "prompt-template",
            "tool-schema",
            "safety-policy",
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    ArtifactReference(kind, f"registry://{kind}/mutable")

    def test_security_sensitive_artifacts_reject_malformed_digest(self) -> None:
        from ai_workflow.provenance import ArtifactReference

        for digest in ("deadbeef", "sha256:deadbeef", "sha512:" + "a" * 128):
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    ArtifactReference(
                        "model",
                        "registry://models/retriever",
                        digest=digest,
                    )

    def test_security_sensitive_artifact_accepts_canonical_sha256_digest(self) -> None:
        from ai_workflow.provenance import ArtifactReference

        digest = "sha256:" + ("ab" * 32)
        artifact = ArtifactReference(
            "model",
            "registry://models/retriever",
            digest=digest,
            version="2026.09",
        )
        self.assertEqual(artifact.digest, digest)

    def test_generic_artifact_remains_backward_compatible_without_digest(self) -> None:
        from ai_workflow.provenance import ArtifactReference

        artifact = ArtifactReference(
            "report",
            "file://benchmark-summary.json",
            version="1",
        )
        self.assertIsNone(artifact.digest)


if __name__ == "__main__":
    unittest.main()
