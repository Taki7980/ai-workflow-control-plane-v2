from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from hypothesis import assume, given, settings, strategies as st

from ai_workflow.provenance import ArtifactReference, LocalRunStore


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class SecurityPropertyTests(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(st.text(max_size=120))
    def test_sensitive_artifact_digest_parser_fails_closed(
        self,
        digest: str,
    ) -> None:
        assume(_SHA256.fullmatch(digest) is None)
        with self.assertRaises(ValueError):
            ArtifactReference(
                "model",
                "registry://models/adversarial",
                digest=digest,
            )

    @settings(max_examples=200, deadline=None)
    @given(st.text(max_size=64))
    def test_run_store_rejects_path_like_run_ids(self, prefix: str) -> None:
        unsafe = f"{prefix}/escape"
        with tempfile.TemporaryDirectory() as td:
            store = LocalRunStore(Path(td))
            with self.assertRaises(ValueError):
                store._path(unsafe)


if __name__ == "__main__":
    unittest.main()
