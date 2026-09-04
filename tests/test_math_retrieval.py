import unittest

from ai_workflow.math_retrieval import (
    BM25Scorer,
    maximal_marginal_relevance,
    reciprocal_rank_fusion,
    tokenize,
)


class TokenizationTests(unittest.TestCase):
    def test_code_identifiers_are_split_into_searchable_terms(self):
        tokens = tokenize("ProcessPayment auth_handler src/api/payments.py")

        self.assertIn("process", tokens)
        self.assertIn("payment", tokens)
        self.assertIn("auth", tokens)
        self.assertIn("handler", tokens)
        self.assertIn("payments", tokens)
    def test_unicode_terms_are_preserved(self):
        tokens = tokenize("résumé 支付 обработка")

        self.assertEqual(tokens, ["résumé", "支付", "обработка"])


class BM25Tests(unittest.TestCase):
    def test_empty_document_does_not_divide_by_zero(self):
        scorer = BM25Scorer()
        scorer.fit([""], ["empty"])

        self.assertEqual(scorer.rank("payment"), [])

    def test_fit_rejects_misaligned_texts_and_objects(self):
        scorer = BM25Scorer()

        with self.assertRaisesRegex(ValueError, "same length"):
            scorer.fit(["one", "two"], ["one"])


class FusionTests(unittest.TestCase):
    def test_consensus_across_rankings_beats_single_first_place(self):
        rankings = [
            ["a", "b", "c"],
            ["b", "c", "a"],
            ["b", "a", "c"],
        ]

        fused = reciprocal_rank_fusion(rankings, key=lambda item: item, k=10)

        self.assertEqual(fused[0][1], "b")
        self.assertEqual({item for _, item in fused}, {"a", "b", "c"})


class MMRTests(unittest.TestCase):
    def test_zero_relevance_candidates_are_not_selected(self):
        texts = ["payment handler", "payment handler wrapper", "banana unrelated"]
        scorer = BM25Scorer()
        scorer.fit(texts, texts)
        query = tokenize("payment")
        scores = [scorer.score_document(query, doc) for doc in scorer.docs]

        ranked = maximal_marginal_relevance(
            query,
            scorer.docs,
            scores,
            max_items=3,
        )

        self.assertEqual(ranked, ["payment handler", "payment handler wrapper"])


if __name__ == "__main__":
    unittest.main()
