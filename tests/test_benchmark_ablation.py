import unittest
from unittest.mock import patch

from ai_workflow.benchmark_ablation import (
    PROFILE_ORDER,
    profile_config,
    run_ablation_suite,
)
from ai_workflow.config import default_config


class BenchmarkAblationTests(unittest.TestCase):
    def test_base_only_disables_specialist_provider_families(self):
        config = default_config()
        config["context"]["semantic"]["command"] = ["semantic-tool"]

        result = profile_config(config, "base_only")

        self.assertEqual(result["context"]["semantic"]["mode"], "off")
        self.assertEqual(result["context"]["semantic"]["command"], "")
        self.assertEqual(result["context"]["crg"]["mode"], "off")
        self.assertEqual(result["context"]["external_retrievers"], [])
        self.assertNotEqual(config["context"]["semantic"]["command"], "")

    def test_adaptive_profile_preserves_original_config(self):
        config = default_config()
        config["context"]["external_retrievers"] = [
            {"name": "x", "command": ["x"], "intents": ["all"]}
        ]

        result = profile_config(config, "adaptive")

        self.assertEqual(result, config)
        self.assertIsNot(result, config)

    @patch("ai_workflow.benchmark_ablation.run_benchmark")
    def test_suite_reports_deltas_against_adaptive(self, run_benchmark):
        run_benchmark.side_effect = [
            {"summary": {"mean_file_recall_at_k": 0.8, "mean_elapsed_ms": 100.0}},
            {"summary": {"mean_file_recall_at_k": 0.6, "mean_elapsed_ms": 50.0}},
        ]

        report = run_ablation_suite(
            ".",
            default_config(),
            [],
            ["adaptive", "base_only"],
        )

        self.assertEqual(report["profiles"], ["adaptive", "base_only"])
        self.assertEqual(
            report["delta_vs_adaptive"]["base_only"]["mean_file_recall_at_k"],
            -0.2,
        )
        self.assertEqual(
            report["delta_vs_adaptive"]["base_only"]["mean_elapsed_ms"],
            -50.0,
        )

    def test_profile_order_is_stable(self):
        self.assertEqual(
            PROFILE_ORDER,
            ("adaptive", "base_only", "base_semantic", "base_structural"),
        )


if __name__ == "__main__":
    unittest.main()
