import tempfile
import unittest
from pathlib import Path

from ai_workflow.observability_export import (
    build_deployment_metrics,
    write_deployment_metrics,
)


REPORT = {
    "policy_id": "policy-123",
    "stage": "canary_5",
    "exposure": {
        "candidate": 5,
        "control": 95,
        "candidate_failure_rate": 0.02,
        "cumulative_candidate_realized_cost": 1.25,
    },
    "drift": {
        "total_variation_distance": 0.1,
        "unknown_context_rate": 0.02,
    },
    "clustered_reward_difference": {
        "clusters": 12,
        "mean": 0.08,
    },
    "gate": {
        "rollback_required": False,
        "safe_to_advance": True,
    },
}


class ObservabilityExportTests(unittest.TestCase):
    def test_export_uses_namespaced_low_cardinality_metrics(self):
        payload = build_deployment_metrics(REPORT)

        names = {metric["name"] for metric in payload["metrics"]}
        self.assertIn(
            "ai_workflow.deployment.guardrail.rollback_required",
            names,
        )
        self.assertIn(
            "ai_workflow.deployment.cluster.reward_difference",
            names,
        )
        for metric in payload["metrics"]:
            self.assertEqual(
                set(metric["attributes"]),
                {"policy_id", "stage"},
            )
        self.assertFalse(
            payload["cardinality_policy"]["task_fingerprint_exported"]
        )
        self.assertFalse(
            payload["cardinality_policy"]["decision_id_exported"]
        )
        self.assertFalse(
            payload["cardinality_policy"]["repository_path_exported"]
        )

    def test_writes_machine_readable_metrics_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "metrics.json"
            written = write_deployment_metrics(path, REPORT)

            self.assertEqual(Path(written), path.resolve())
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
