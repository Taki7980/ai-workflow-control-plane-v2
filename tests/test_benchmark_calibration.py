import unittest

from ai_workflow.benchmark_calibration import (
    calibrate_sufficiency_threshold,
    deterministic_stratified_split,
    threshold_metrics,
)


class BenchmarkCalibrationTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "task": "positive-a",
                "task_type": "code2test",
                "control_type": "positive",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.92,
            },
            {
                "task": "positive-b",
                "task_type": "trace2code",
                "control_type": "positive",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.82,
            },
            {
                "task": "positive-c",
                "task_type": "edit2ripple",
                "control_type": "positive",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.76,
            },
            {
                "task": "positive-d",
                "task_type": "comment2context",
                "control_type": "positive",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.70,
            },
            {
                "task": "control-a",
                "task_type": "natural_no_gold",
                "control_type": "natural_no_gold",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.38,
            },
            {
                "task": "control-b",
                "task_type": "natural_no_gold",
                "control_type": "natural_no_gold",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.44,
            },
            {
                "task": "control-c",
                "task_type": "wrong_repo",
                "control_type": "wrong_repo",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.55,
            },
            {
                "task": "control-d",
                "task_type": "wrong_repo",
                "control_type": "wrong_repo",
                "repository_path": ".",
                "retrieval_sufficiency_score": 0.61,
            },
        ]

    def test_split_is_deterministic_and_disjoint(self):
        rows = self._rows()

        first = deterministic_stratified_split(
            rows,
            calibration_fraction=0.5,
        )
        second = deterministic_stratified_split(
            rows,
            calibration_fraction=0.5,
        )

        self.assertEqual(first, second)
        calibration, holdout = first
        self.assertTrue(calibration)
        self.assertTrue(holdout)
        self.assertFalse(
            {id(row) for row in calibration}
            & {id(row) for row in holdout}
        )

    def test_false_accept_cost_is_reflected_in_metrics(self):
        rows = [
            {
                "control_type": "positive",
                "retrieval_sufficiency_score": 0.8,
            },
            {
                "control_type": "natural_no_gold",
                "retrieval_sufficiency_score": 0.7,
            },
        ]

        result = threshold_metrics(
            rows,
            0.6,
            false_accept_cost=5,
            false_reject_cost=1,
        )

        self.assertEqual(result["false_accepts"], 1)
        self.assertEqual(result["false_rejects"], 0)
        self.assertEqual(result["total_cost"], 5.0)

    def test_calibration_remains_advisory_and_uses_holdout(self):
        report = {"cases": self._rows()}

        result = calibrate_sufficiency_threshold(
            report,
            calibration_fraction=0.5,
            false_accept_cost=5,
            false_reject_cost=1,
        )

        self.assertEqual(result["status"], "advisory_only")
        self.assertGreater(result["split"]["calibration_cases"], 0)
        self.assertGreater(result["split"]["holdout_cases"], 0)
        self.assertGreaterEqual(result["threshold"], 0.0)
        self.assertLessEqual(result["threshold"], 1.0)


if __name__ == "__main__":
    unittest.main()
