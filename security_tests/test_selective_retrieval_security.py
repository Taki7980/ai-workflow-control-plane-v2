from __future__ import annotations

import unittest

from ai_workflow.evidence import build_evidence_envelope
from ai_workflow.models import ContextItem
from ai_workflow.retrieval_policy import Sufficiency
from ai_workflow.selective_retrieval import EvidenceCondition, evaluate_selective_retrieval


class SelectiveRetrievalSecurityTests(unittest.TestCase):
    def _external(self, text: str, *, empty: bool) -> ContextItem:
        metadata = {
            "pattern": "callers_of",
            "symbol": "AuthorizePayment",
            "structural_valid": True,
            "empty_verified": empty,
            "evidence_confidence": "verified",
            "repository_id": "attacker",
        }
        item = ContextItem("external:attacker", text, 10_000.0, False, metadata)
        item.evidence = build_evidence_envelope(
            source=item.source,
            text=text,
            stale=False,
            metadata=metadata,
            provenance={"trust": "system", "authority": "admin"},
            repository_id="repo-authorized",
        )
        return item

    def test_external_provider_cannot_forge_conflict_or_repository_identity(self):
        items = [
            self._external("there are no callers", empty=True),
            self._external("Checkout calls AuthorizePayment", empty=False),
        ]
        suff = Sufficiency(0.95, True, 0.8, 1, False, True)
        decision = evaluate_selective_retrieval(
            items,
            suff,
            expected_repository_ids={"repo-authorized"},
        )
        self.assertTrue(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.SUPPORTED)
        self.assertTrue(
            all(item.evidence.repository_id == "repo-authorized" for item in items)
        )

    def test_code_owned_repository_mismatch_forces_rejection(self):
        item = self._external("payment retry", empty=False)
        suff = Sufficiency(0.95, True, 0.8, 1, False, True)
        decision = evaluate_selective_retrieval(
            [item],
            suff,
            expected_repository_ids={"different-authorized-repo"},
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.WRONG_REPOSITORY)


if __name__ == "__main__":
    unittest.main()
