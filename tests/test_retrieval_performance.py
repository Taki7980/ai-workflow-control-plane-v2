from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from ai_workflow.context_selection import select_context
from ai_workflow.math_retrieval import BM25Scorer, tokenize
from ai_workflow.models import ContextItem


ROOT = Path(__file__).resolve().parents[1]


class BM25PerformanceContractTests(unittest.TestCase):
    def test_fit_precomputes_term_frequencies(self) -> None:
        scorer = BM25Scorer()
        scorer.fit(["payment payment retry"], ["doc"])

        self.assertEqual(
            scorer.docs[0].term_freq,
            {"payment": 2, "retry": 1},
        )

    def test_scoring_does_not_rescan_token_list(self) -> None:
        class NoCountList(list[str]):
            def count(self, value: str) -> int:
                raise AssertionError("BM25 scoring must use precomputed term frequencies")

        scorer = BM25Scorer()
        scorer.fit(["payment payment retry"], ["doc"])
        doc = scorer.docs[0]
        doc.tokens = NoCountList(doc.tokens)

        score = scorer.score_document(tokenize("payment retry"), doc)

        self.assertGreater(score, 0.0)


class TokenAwareSelectorContractTests(unittest.TestCase):
    class UnevenEstimator:
        def estimate(self, text: str) -> int:
            if "compact" in text:
                return 1
            if "verbose" in text:
                return 10
            return 2

    class OneTokenEstimator:
        def estimate(self, text: str) -> int:
            return 1 if text else 0

    def test_token_budget_prefers_lower_token_cost_at_equal_relevance(self) -> None:
        items = [
            ContextItem("verbose", "payment verbose", 5.0),
            ContextItem("compact", "payment compact", 5.0),
        ]

        selected, diagnostics = select_context(
            "payment",
            items,
            budget_chars=100,
            budget_tokens=1,
            token_estimator=self.UnevenEstimator(),
            config={"context": {"selector": {"tight_budget_fraction": 0.5}}},
        )

        self.assertEqual([item.source for item in selected], ["compact"])
        self.assertEqual(diagnostics["used_tokens"], 1)
        self.assertEqual(diagnostics["budget_tokens"], 1)
        self.assertLessEqual(diagnostics["used_chars"], 100)

    def test_token_budget_never_bypasses_character_hard_cap(self) -> None:
        item = ContextItem("compact", "payment compact evidence", 10.0)

        selected, diagnostics = select_context(
            "payment",
            [item],
            budget_chars=8,
            budget_tokens=10,
            token_estimator=self.OneTokenEstimator(),
            config={"context": {"selector": {"tight_budget_fraction": 0.5}}},
        )

        self.assertEqual(selected, [])
        self.assertEqual(diagnostics["used_chars"], 0)
        self.assertEqual(diagnostics["used_tokens"], 0)


class RetrievalPerformanceScriptTests(unittest.TestCase):
    def test_reference_parity_benchmark_passes_and_reports_timings(self) -> None:
        script = ROOT / "scripts" / "check_retrieval_performance.py"
        self.assertTrue(script.is_file(), "retrieval performance checker must exist")

        proc = subprocess.run(
            [sys.executable, str(script), "--documents", "120", "--queries", "12"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ranking_parity"])
        self.assertLessEqual(payload["max_score_delta"], 1e-12)
        self.assertEqual(payload["documents"], 120)
        self.assertEqual(payload["queries"], 12)
        self.assertGreaterEqual(payload["reference_elapsed_ms"], 0.0)
        self.assertGreaterEqual(payload["optimized_elapsed_ms"], 0.0)
        self.assertIn("observed_speedup", payload)


if __name__ == "__main__":
    unittest.main()
