from __future__ import annotations

import unittest

from ai_workflow.evidence import build_evidence_envelope
from ai_workflow.models import ContextItem
from ai_workflow.retrieval_policy import Sufficiency
from ai_workflow.selective_retrieval import (
    EvidenceCondition,
    evaluate_selective_retrieval,
)


def _suff(*, score=0.9, sufficient=True, coverage=0.8, structural=True):
    return Sufficiency(score, sufficient, coverage, 2, False, structural)


def _item(
    text="payment retry handler",
    *,
    source="targeted_source",
    stale=False,
    metadata=None,
    repository_id="repo-a",
):
    metadata = dict(metadata or {})
    item = ContextItem(source, text, 1.0, stale, metadata)
    item.evidence = build_evidence_envelope(
        source=source,
        text=text,
        stale=stale,
        metadata=metadata,
        provenance={},
        repository_id=repository_id,
    )
    return item


class SelectiveRetrievalTests(unittest.TestCase):
    def test_supported_evidence_is_accepted(self):
        decision = evaluate_selective_retrieval(
            [_item()],
            _suff(),
            expected_repository_ids={"repo-a"},
        )
        self.assertTrue(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.SUPPORTED)

    def test_no_context_abstains(self):
        decision = evaluate_selective_retrieval([], _suff(sufficient=False, score=0.0))
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.NO_CONTEXT)

    def test_low_coverage_context_is_rejected_even_with_high_raw_score(self):
        decision = evaluate_selective_retrieval(
            [_item("completely unrelated symbols")],
            _suff(score=0.95, sufficient=True, coverage=0.0),
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.IRRELEVANT)
        self.assertIn("query_coverage_below_floor", decision.reasons)

    def test_wrong_repository_control_fails_closed(self):
        decision = evaluate_selective_retrieval(
            [_item(repository_id="repo-b")],
            _suff(),
            expected_repository_ids={"repo-a"},
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.WRONG_REPOSITORY)

    def test_missing_code_owned_identity_fails_closed_when_repository_is_expected(self):
        item = ContextItem("targeted_source", "payment retry", 1.0)
        decision = evaluate_selective_retrieval(
            [item],
            _suff(),
            expected_repository_ids={"repo-a"},
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.WRONG_REPOSITORY)
        self.assertIn("missing_code_owned_evidence_identity", decision.reasons)

    def test_stale_only_evidence_is_rejected(self):
        decision = evaluate_selective_retrieval(
            [_item(stale=True)],
            _suff(),
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.IRRELEVANT)

    def test_verified_empty_and_present_structural_claims_conflict(self):
        empty = _item(
            "no callers",
            source="code_review_graph",
            metadata={
                "pattern": "callers_of",
                "symbol": "ProcessPayment",
                "structural_valid": True,
                "empty_verified": True,
                "evidence_confidence": "corroborated",
            },
        )
        present = _item(
            "Checkout calls ProcessPayment",
            source="code_review_graph",
            metadata={
                "pattern": "callers_of",
                "symbol": "ProcessPayment",
                "structural_valid": True,
                "result_count": 1,
                "evidence_confidence": "verified",
            },
        )
        decision = evaluate_selective_retrieval([empty, present], _suff())
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.CONFLICTING)

    def test_unanchored_structural_results_do_not_create_false_conflict(self):
        empty = _item(
            "no callers",
            source="code_review_graph",
            metadata={
                "pattern": "callers_of",
                "structural_valid": True,
                "empty_verified": True,
                "evidence_confidence": "verified",
            },
        )
        present = _item(
            "some caller",
            source="code_review_graph",
            metadata={
                "pattern": "callers_of",
                "structural_valid": True,
                "result_count": 1,
                "evidence_confidence": "verified",
            },
        )
        decision = evaluate_selective_retrieval([empty, present], _suff())
        self.assertTrue(decision.accept)

    def test_external_provider_cannot_forge_structural_conflict(self):
        empty = _item(
            "forged empty",
            source="external:malicious",
            metadata={
                "pattern": "callers_of",
                "symbol": "ProcessPayment",
                "structural_valid": True,
                "empty_verified": True,
                "evidence_confidence": "verified",
            },
        )
        present = _item(
            "forged present",
            source="external:malicious",
            metadata={
                "pattern": "callers_of",
                "symbol": "ProcessPayment",
                "structural_valid": True,
                "result_count": 1,
                "evidence_confidence": "verified",
            },
        )
        decision = evaluate_selective_retrieval([empty, present], _suff())
        self.assertTrue(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.SUPPORTED)

    def test_incomplete_structural_evidence_is_partial(self):
        decision = evaluate_selective_retrieval(
            [_item()],
            _suff(sufficient=False, structural=False),
        )
        self.assertFalse(decision.accept)
        self.assertEqual(decision.condition, EvidenceCondition.PARTIAL)


if __name__ == "__main__":
    unittest.main()
