import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.benchmark_intervention import (
    deterministic_non_gold_sample,
    run_intervention_runner,
    run_seed_interventions,
    seed_metrics,
)


class BenchmarkInterventionTests(unittest.TestCase):
    def test_random_non_gold_is_deterministic_and_excludes_gold(self):
        files = ["a.py", "b.py", "c.py", "d.py"]
        gold = ["b.py"]

        first = deterministic_non_gold_sample(files, gold, "case-1", 2)
        second = deterministic_non_gold_sample(files, gold, "case-1", 2)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertNotIn("b.py", first)

    def test_seed_metrics_report_file_level_f1(self):
        metrics = seed_metrics(
            ["src/a.py", "src/noise.py"],
            ["src/a.py", "src/b.py"],
        )

        self.assertEqual(metrics["precision"], 0.5)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertEqual(metrics["f1"], 0.5)

    def test_runner_protocol_returns_trajectory_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = (
                "import json; "
                "print(json.dumps({"
                "'success': True, "
                "'trajectory_events': ["
                "{'kind':'explored','file':'src/a.py','step':1},"
                "{'kind':'utilized','file':'src/a.py','step':2}"
                "]}))"
            )
            intervention = {
                "task": "fix a",
                "task_type": "edit2ripple",
                "repository_path": ".",
                "base_commit": "a" * 40,
                "seed_mode": "retrieval",
                "seed_files": ["src/a.py"],
                "gold_files": ["src/a.py"],
            }

            result = run_intervention_runner(
                root,
                intervention,
                [sys.executable, "-c", script],
                timeout_seconds=10,
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["success"])
        self.assertEqual(
            result["trajectory"]["utilization_recall"],
            1.0,
        )
        self.assertEqual(
            result["trajectory"]["seed_gold_recall"],
            1.0,
        )

    @patch(
        "ai_workflow.benchmark_intervention.run_intervention_runner"
    )
    def test_seed_run_reports_paired_delta_against_random(self, runner):
        def fake_runner(root, intervention, command, **kwargs):
            mode = intervention["seed_mode"]
            value = 0.8 if mode == "retrieval" else 0.4
            return {
                "status": "ok",
                "success": True,
                "trajectory": {
                    "seed_gold_recall": value,
                    "exploration_recall": value,
                    "utilization_recall": value,
                    "context_utilization_rate": value,
                    "duplicate_exploration_rate": 1 - value,
                    "post_seed_exploration_unique_files": (
                        1 if mode == "retrieval" else 3
                    ),
                },
            }

        runner.side_effect = fake_runner
        manifest = {
            "seed_k": 1,
            "interventions": [
                {
                    "case_index": 1,
                    "task": "task",
                    "repository_path": ".",
                    "base_commit": "a" * 40,
                    "seed_mode": "random_non_gold",
                    "seed_files": ["noise.py"],
                    "gold_files": ["gold.py"],
                    "seed_metrics": seed_metrics(
                        ["noise.py"],
                        ["gold.py"],
                    ),
                },
                {
                    "case_index": 1,
                    "task": "task",
                    "repository_path": ".",
                    "base_commit": "a" * 40,
                    "seed_mode": "retrieval",
                    "seed_files": ["gold.py"],
                    "gold_files": ["gold.py"],
                    "seed_metrics": seed_metrics(
                        ["gold.py"],
                        ["gold.py"],
                    ),
                },
            ],
        }

        result = run_seed_interventions(
            Path("."),
            manifest,
            ["runner"],
        )

        delta = result["paired_delta_vs_random_non_gold"]["retrieval"]
        self.assertEqual(delta["paired_cases"], 1)
        self.assertEqual(
            delta["mean_delta_utilization_recall"],
            0.4,
        )
        self.assertEqual(
            delta["mean_delta_post_seed_exploration_unique_files"],
            -2.0,
        )


if __name__ == "__main__":
    unittest.main()
