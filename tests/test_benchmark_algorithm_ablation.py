import unittest
from unittest.mock import patch

from ai_workflow.benchmark_algorithm_ablation import (
    ALGORITHM_PROFILE_ORDER,
    algorithm_profile_config,
    run_algorithm_ablation_suite,
)
from ai_workflow.config import default_config


class BenchmarkAlgorithmAblationTests(unittest.TestCase):
    def test_profiles_change_only_requested_algorithm_controls(self):
        config = default_config()

        source = algorithm_profile_config(config, "source_rank")
        selector = algorithm_profile_config(config, "selector_off")
        budget = algorithm_profile_config(config, "fixed_budget")
        early = algorithm_profile_config(config, "no_early_stop")

        self.assertEqual(
            source["context"]["experiments"]["hybrid_ranker"],
            "source",
        )
        self.assertFalse(selector["context"]["selector"]["enabled"])
        self.assertFalse(budget["context"]["adaptive_budget"]["enabled"])
        self.assertTrue(
            early["context"]["experiments"][
                "disable_early_sufficiency_gate"
            ]
        )
        self.assertNotIn("experiments", config["context"])

    def test_mmr_profiles_expose_parameter_sensitivity(self):
        config = default_config()

        low = algorithm_profile_config(config, "rrf_mmr_050")
        production = algorithm_profile_config(config, "rrf_mmr_075")
        high = algorithm_profile_config(config, "rrf_mmr_090")

        self.assertEqual(low["context"]["experiments"]["mmr_lambda"], 0.50)
        self.assertEqual(
            production["context"]["experiments"]["mmr_lambda"],
            0.75,
        )
        self.assertEqual(high["context"]["experiments"]["mmr_lambda"], 0.90)

    @patch(
        "ai_workflow.benchmark_algorithm_ablation.run_benchmark"
    )
    def test_suite_reports_deltas_against_adaptive_math(self, run_benchmark):
        run_benchmark.side_effect = [
            {
                "summary": {
                    "mean_file_recall_at_k": 0.8,
                    "mean_elapsed_ms": 100.0,
                }
            },
            {
                "summary": {
                    "mean_file_recall_at_k": 0.6,
                    "mean_elapsed_ms": 75.0,
                }
            },
        ]

        result = run_algorithm_ablation_suite(
            ".",
            default_config(),
            [],
            ["adaptive_math", "rrf_only"],
        )

        delta = result["delta_vs_adaptive_math"]["rrf_only"]
        self.assertEqual(delta["mean_file_recall_at_k"], -0.2)
        self.assertEqual(delta["mean_elapsed_ms"], -25.0)

    def test_profile_order_includes_core_stage3_controls(self):
        self.assertIn("bm25_rank", ALGORITHM_PROFILE_ORDER)
        self.assertIn("rrf_only", ALGORITHM_PROFILE_ORDER)
        self.assertIn("rrf_mmr_075", ALGORITHM_PROFILE_ORDER)
        self.assertIn("selector_off", ALGORITHM_PROFILE_ORDER)
        self.assertIn("no_early_stop", ALGORITHM_PROFILE_ORDER)


if __name__ == "__main__":
    unittest.main()
