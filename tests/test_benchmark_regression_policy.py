from __future__ import annotations

import unittest


class BenchmarkRegressionPolicyTests(unittest.TestCase):
    def test_correctness_floor_is_blocking(self):
        from ai_workflow.benchmark_regression import check_regression

        baseline = {"schema_version": 1, "minimum": {"lane_accuracy": 0.8}, "maximum_regression": {}, "by_query_type": {}}
        current = {"summary": {"lane_accuracy": 0.79}, "by_query_type": {}}
        report = check_regression(baseline, current)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failures"][0]["metric"], "lane_accuracy")

    def test_noisy_efficiency_uses_relative_tolerance(self):
        from ai_workflow.benchmark_regression import check_regression

        baseline = {
            "schema_version": 1,
            "minimum": {},
            "maximum_regression": {"mean_relevant_item_density": {"baseline": 0.40, "relative_tolerance": 0.10, "direction": "higher"}},
            "by_query_type": {},
        }
        acceptable = {"summary": {"mean_relevant_item_density": 0.37}, "by_query_type": {}}
        failing = {"summary": {"mean_relevant_item_density": 0.34}, "by_query_type": {}}
        self.assertTrue(check_regression(baseline, acceptable)["ok"])
        self.assertFalse(check_regression(baseline, failing)["ok"])

    def test_per_query_floor_cannot_be_hidden_by_overall_mean(self):
        from ai_workflow.benchmark_regression import check_regression

        baseline = {
            "schema_version": 1,
            "minimum": {},
            "maximum_regression": {},
            "by_query_type": {"security": {"lane_accuracy": 1.0, "intent_accuracy": 0.5}},
        }
        current = {
            "summary": {"lane_accuracy": 1.0},
            "by_query_type": {"security": {"lane_accuracy": 0.5, "intent_accuracy": 1.0}},
        }
        report = check_regression(baseline, current)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failures"][0]["query_type"], "security")


class BenchmarkDistributionTests(unittest.TestCase):
    def test_percentiles_report_p50_p95_p99(self):
        from ai_workflow.benchmark_regression import latency_percentiles

        result = latency_percentiles([1, 2, 3, 4, 100])
        self.assertEqual(result["p50"], 3.0)
        self.assertGreaterEqual(result["p95"], 4.0)
        self.assertEqual(result["p99"], 100.0)

    def test_profile_decision_is_measurement_driven(self):
        from ai_workflow.profiling import daemon_profile_decision

        strong = daemon_profile_decision([100, 100, 100], [50, 50, 50], material_benefit_fraction=0.25)
        weak = daemon_profile_decision([100, 100, 100], [90, 90, 90], material_benefit_fraction=0.25)
        self.assertTrue(strong["implement_daemon"])
        self.assertFalse(weak["implement_daemon"])
        self.assertEqual(strong["threshold_fraction"], 0.25)


if __name__ == "__main__":
    unittest.main()
