import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.benchmark_trajectory import (
    load_trajectory_events,
    trajectory_metrics,
)


class BenchmarkTrajectoryTests(unittest.TestCase):
    def test_metrics_separate_explored_from_utilized_context(self):
        events = [
            {"kind": "seed", "file": "src/a.py", "step": 0},
            {"kind": "explored", "file": "src/a.py", "step": 1},
            {"kind": "explored", "file": "src/noise.py", "step": 2},
            {"kind": "explored", "file": "src/noise.py", "step": 3},
            {"kind": "utilized", "file": "src/a.py", "step": 4},
        ]

        metrics = trajectory_metrics(events, ["src/a.py", "src/b.py"])

        self.assertEqual(metrics["seed_gold_recall"], 0.5)
        self.assertEqual(metrics["exploration_recall"], 0.5)
        self.assertEqual(metrics["utilization_recall"], 0.5)
        self.assertEqual(metrics["utilization_precision"], 1.0)
        self.assertAlmostEqual(metrics["duplicate_exploration_rate"], 1 / 3)
        self.assertEqual(metrics["first_gold_exploration_step"], 1)
        self.assertEqual(metrics["first_gold_utilization_step"], 4)
        self.assertEqual(metrics["post_seed_exploration_unique_files"], 2)

    def test_jsonl_trajectory_loads_inside_benchmark_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "traces" / "case.jsonl"
            path.parent.mkdir()
            path.write_text(
                json.dumps({"kind": "explored", "file": "src/a.py", "step": 1})
                + "\n",
                encoding="utf-8",
            )

            events = load_trajectory_events(
                root,
                {"trajectory_file": "traces/case.jsonl"},
            )

        self.assertEqual(
            events,
            [{"kind": "explored", "file": "src/a.py", "step": 1}],
        )

    def test_trajectory_file_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "inside the benchmark root"):
                load_trajectory_events(
                    Path(temp),
                    {"trajectory_file": "../outside.json"},
                )


if __name__ == "__main__":
    unittest.main()
