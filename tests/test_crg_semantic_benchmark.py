from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.crg_semantic_benchmark import (
    score_ranked_rows,
    validate_cases,
)
from scripts.check_crg_semantic_regression import check_regression


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

    def test_gold_matching_ignores_unrelated_metadata_text(self) -> None:
        metrics = score_ranked_rows(
            [
                {
                    "file_path": "python/beta.py",
                    "name": "helper",
                    "debug_note": "python/alpha.py::helper",
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

    def test_measured_baseline_accepts_equal_or_better_report(self) -> None:
        baseline = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version": "2.3.8",
            "minimums": {
                "mean_recall_at_k": 0.6,
                "stale_graph_block_rate": 1.0,
            },
            "maximums": {
                "latency_p95_ms": 500.0,
            },
            "category_minimum_recall": {
                "cross_language": 1.0,
            },
            "known_misses": ["py-alias-call", "rename_delete"],
        }
        report = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version_actual": "code-review-graph 2.3.8",
            "summary": {
                "mean_recall_at_k": 0.7,
                "stale_graph_block_rate": 1.0,
                "latency_p95_ms": 300.0,
            },
            "by_category": {
                "cross_language": {"mean_recall_at_k": 1.0},
            },
            "cases": [{"case_id": "py-alias-call"}],
            "controls": {"rename_delete": {"passed": False}},
        }

        self.assertEqual(check_regression(baseline, report), [])

    def test_regression_rejects_version_prefix_collision(self) -> None:
        baseline = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version": "2.3.8",
            "minimums": {},
            "maximums": {},
            "category_minimum_recall": {},
        }
        report = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version_actual": "code-review-graph 2.3.80",
            "summary": {},
            "by_category": {},
            "cases": [],
            "controls": {},
        }

        failures = check_regression(baseline, report)
        self.assertTrue(any("CRG version mismatch" in row for row in failures))

    def test_measured_baseline_reports_semantic_regression(self) -> None:
        baseline = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version": "2.3.8",
            "minimums": {"mean_mrr": 0.6},
            "maximums": {"latency_p95_ms": 500.0},
            "category_minimum_recall": {
                "cross_language": 1.0,
            },
        }
        report = {
            "benchmark": "crg-semantic-golden-v1",
            "crg_version_actual": "code-review-graph 2.3.8",
            "summary": {
                "mean_mrr": 0.5,
                "latency_p95_ms": 700.0,
            },
            "by_category": {
                "cross_language": {"mean_recall_at_k": 0.5},
            },
            "cases": [],
            "controls": {},
        }

        failures = check_regression(baseline, report)
        self.assertTrue(any("mean_mrr regressed" in row for row in failures))
        self.assertTrue(any("latency_p95_ms regressed" in row for row in failures))
        self.assertTrue(any("cross_language recall regressed" in row for row in failures))

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
