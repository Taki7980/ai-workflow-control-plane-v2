import unittest

from ai_workflow.benchmark_statistics import (
    analyze_seed_report,
    bootstrap_mean_ci,
    paired_effect_summary,
)


class BenchmarkStatisticsTests(unittest.TestCase):
    def test_bootstrap_is_deterministic_for_fixed_seed(self):
        first = bootstrap_mean_ci(
            [0.1, 0.2, 0.3, 0.4],
            resamples=500,
            seed=7,
        )
        second = bootstrap_mean_ci(
            [0.1, 0.2, 0.3, 0.4],
            resamples=500,
            seed=7,
        )

        self.assertEqual(first, second)
        self.assertLessEqual(first["ci_low"], first["mean"])
        self.assertGreaterEqual(first["ci_high"], first["mean"])

    def test_paired_effect_counts_wins_ties_and_losses(self):
        result = paired_effect_summary(
            [0.2, 0.1, 0.0, -0.1],
            resamples=200,
            seed=3,
        )

        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["ties"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["n"], 4)

    def test_seed_report_statistics_use_paired_random_control(self):
        report = {
            "results": [
                {
                    "case_index": 1,
                    "task_type": "code2test",
                    "seed_mode": "random_non_gold",
                    "runner": {
                        "status": "ok",
                        "trajectory": {
                            "utilization_recall": 0.2,
                            "exploration_recall": 0.3,
                            "context_utilization_rate": 0.4,
                            "duplicate_exploration_rate": 0.3,
                            "post_seed_exploration_unique_files": 5,
                        },
                    },
                },
                {
                    "case_index": 1,
                    "task_type": "code2test",
                    "seed_mode": "retrieval",
                    "runner": {
                        "status": "ok",
                        "trajectory": {
                            "utilization_recall": 0.7,
                            "exploration_recall": 0.6,
                            "context_utilization_rate": 0.8,
                            "duplicate_exploration_rate": 0.1,
                            "post_seed_exploration_unique_files": 2,
                        },
                    },
                },
                {
                    "case_index": 2,
                    "task_type": "trace2code",
                    "seed_mode": "random_non_gold",
                    "runner": {
                        "status": "ok",
                        "trajectory": {
                            "utilization_recall": 0.1,
                            "exploration_recall": 0.2,
                            "context_utilization_rate": 0.3,
                            "duplicate_exploration_rate": 0.4,
                            "post_seed_exploration_unique_files": 6,
                        },
                    },
                },
                {
                    "case_index": 2,
                    "task_type": "trace2code",
                    "seed_mode": "retrieval",
                    "runner": {
                        "status": "ok",
                        "trajectory": {
                            "utilization_recall": 0.5,
                            "exploration_recall": 0.5,
                            "context_utilization_rate": 0.6,
                            "duplicate_exploration_rate": 0.2,
                            "post_seed_exploration_unique_files": 3,
                        },
                    },
                },
            ]
        }

        result = analyze_seed_report(
            report,
            resamples=200,
            seed=11,
            stratify=["task_type"],
        )

        utilization = result["comparisons"]["retrieval"][
            "utilization_recall"
        ]
        self.assertEqual(utilization["n"], 2)
        self.assertAlmostEqual(utilization["mean"], 0.45)
        self.assertIn("code2test", result["stratified"]["task_type"])
        self.assertIn("trace2code", result["stratified"]["task_type"])


if __name__ == "__main__":
    unittest.main()
