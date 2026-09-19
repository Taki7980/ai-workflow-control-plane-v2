from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_workflow.crg_semantic_benchmark import (
    score_ranked_rows,
    validate_cases,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "benchmarks" / "crg-semantic-v1" / "cases.json"


class CrgSemanticBenchmarkContractTests(unittest.TestCase):
    def test_gold_scoring_reports_precision_recall_and_mrr(self) -> None:
        rows = [
            {
                "relative_path": "python/noise.py",
                "name": "noise",
            },
            {
                "relative_path": "python/alpha.py",
                "name": "helper",
            },
            {
                "relative_path": "python/beta.py",
                "name": "helper",
            },
        ]
        metrics = score_ranked_rows(
            rows,
            [
                {
                    "path_contains": "python/alpha.py",
                    "name_contains": "helper",
                }
            ],
        )

        self.assertEqual(metrics["returned"], 3)
        self.assertEqual(metrics["matched_gold"], 1)
        self.assertAlmostEqual(metrics["precision_at_k"], 1 / 3, places=4)
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertTrue(metrics["full_recall"])

    def test_duplicate_symbol_gold_requires_path_and_name(self) -> None:
        metrics = score_ranked_rows(
            [
                {
                    "relative_path": "python/beta.py",
                    "name": "helper",
                }
            ],
            [
                {
                    "path_contains": "python/alpha.py",
                    "name_contains": "helper",
                }
            ],
        )

        self.assertEqual(metrics["precision_at_k"], 0.0)
        self.assertEqual(metrics["recall_at_k"], 0.0)
        self.assertEqual(metrics["mrr"], 0.0)

    def test_corpus_covers_required_semantic_categories(self) -> None:
        payload = json.loads(CASES.read_text(encoding="utf-8"))
        cases = validate_cases(payload)
        categories = {str(case["category"]) for case in cases}

        self.assertTrue(
            {
                "alias",
                "duplicate_symbol",
                "inheritance_override",
                "callback",
                "async_chain",
                "dynamic_import",
                "generated_code",
                "tests",
                "cross_language",
            }.issubset(categories)
        )
        self.assertGreaterEqual(len(cases), 10)

    def test_corpus_uses_versioned_schema_and_crg_pin(self) -> None:
        payload = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["crg_version"], "2.3.8")
        validate_cases(payload)

    def test_invalid_or_duplicate_cases_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate_cases({"schema_version": 2, "cases": []})

        duplicate = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "dup",
                    "category": "x",
                    "language": "python",
                    "pattern": "callers_of",
                    "target": "f",
                    "query": "q",
                    "gold": [{"name_contains": "g"}],
                },
                {
                    "case_id": "dup",
                    "category": "y",
                    "language": "python",
                    "pattern": "callees_of",
                    "target": "g",
                    "query": "q2",
                    "gold": [{"name_contains": "f"}],
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_cases(duplicate)


if __name__ == "__main__":
    unittest.main()
