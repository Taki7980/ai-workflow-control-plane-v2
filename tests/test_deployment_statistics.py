import unittest

from ai_workflow.deployment_statistics import clustered_reward_difference


def row(cluster, assignment, reward):
    return {
        "task_fingerprint": cluster,
        "deployment": {
            "assignment": assignment,
            "candidate_probability": 0.5,
        },
        "outcome": {
            "verified": True,
            "reward": reward,
        },
    }


class DeploymentStatisticsTests(unittest.TestCase):
    def test_cluster_bootstrap_resamples_whole_task_clusters(self):
        rows = []
        for index in range(8):
            cluster = f"task-{index}"
            rows.append(row(cluster, "candidate", 0.0))
            rows.append(row(cluster, "control", 1.0))

        first = clustered_reward_difference(
            rows,
            confidence=0.95,
            resamples=500,
            seed=7,
        )
        second = clustered_reward_difference(
            rows,
            confidence=0.95,
            resamples=500,
            seed=7,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["clusters"], 8)
        self.assertEqual(first["rows"], 16)
        self.assertEqual(first["largest_cluster"], 2)
        self.assertLess(first["ci_high"], 0.0)

    def test_single_cluster_is_not_treated_as_independent_rows(self):
        rows = [
            row("same-task", "candidate", 1.0),
            row("same-task", "control", 0.0),
            row("same-task", "candidate", 1.0),
        ]

        result = clustered_reward_difference(rows, resamples=100)

        self.assertEqual(result["status"], "insufficient_clusters")
        self.assertEqual(result["clusters"], 1)
        self.assertEqual(result["rows"], 3)
        self.assertIsNone(result["ci_low"])
        self.assertIsNone(result["ci_high"])


if __name__ == "__main__":
    unittest.main()
