import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai_workflow.benchmark_protocol import (
    context_item_file,
    file_retrieval_metrics,
    repository_control_metrics,
    snapshot_status,
    validate_benchmark_cases,
)
from ai_workflow.models import ContextItem


class BenchmarkProtocolTests(unittest.TestCase):
    def test_file_metrics_use_exact_file_level_gold(self):
        items = [
            ContextItem(
                "lightweight_index",
                json.dumps({"symbol": "helper", "file": "ai_workflow/other.py"}),
            ),
            ContextItem(
                "lightweight_index",
                json.dumps({"symbol": "run_benchmark", "file": "ai_workflow/benchmark.py"}),
            ),
            ContextItem(
                "targeted_source",
                "tests/test_benchmark_metrics.py:12: class RetrievalMetricTests",
            ),
        ]

        metrics = file_retrieval_metrics(
            items,
            ["ai_workflow/benchmark.py", "tests/test_benchmark_metrics.py"],
            k=3,
        )

        self.assertEqual(metrics["matched_gold_files"], [
            "ai_workflow/benchmark.py",
            "tests/test_benchmark_metrics.py",
        ])
        self.assertAlmostEqual(metrics["precision_at_k"], 2 / 3)
        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertGreater(metrics["file_f1"], 0.0)

    def test_context_item_file_supports_targeted_source_lines(self):
        item = ContextItem(
            "targeted_source",
            "ai_workflow/context_broker.py:88: def lightweight(...):",
        )
        self.assertEqual(
            context_item_file(item),
            "ai_workflow/context_broker.py",
        )

    def test_repository_controls_detect_forbidden_identity(self):
        items = [
            ContextItem(
                "semantic",
                "candidate",
                metadata={"repository_id": "repo-safe"},
            ),
            ContextItem(
                "semantic",
                "candidate 2",
                provenance={"repository_id": "repo-forbidden"},
            ),
        ]

        metrics = repository_control_metrics(
            items,
            ["repo-forbidden"],
            k=2,
        )

        self.assertEqual(metrics["contamination_count"], 1)
        self.assertEqual(metrics["identity_coverage"], 1.0)

    def test_research_protocol_requires_gold_for_positive_tasks(self):
        with self.assertRaisesRegex(ValueError, "requires gold_files"):
            validate_benchmark_cases(
                [
                    {
                        "task": "find the test",
                        "task_type": "code2test",
                        "base_commit": "a" * 40,
                        "retrieval_k": 5,
                    }
                ],
                require_research_protocol=True,
            )

    def test_wrong_repo_control_requires_forbidden_identity_in_strict_mode(self):
        with self.assertRaisesRegex(ValueError, "forbidden_repositories"):
            validate_benchmark_cases(
                [
                    {
                        "task": "find a subsystem that is not in this repo",
                        "task_type": "no_gold",
                        "control_type": "wrong_repo",
                        "base_commit": "b" * 40,
                        "retrieval_k": 5,
                    }
                ],
                require_research_protocol=True,
            )

    @patch("ai_workflow.benchmark_protocol.subprocess.run")
    def test_snapshot_status_matches_declared_head(self, run):
        run.return_value = Mock(returncode=0, stdout=("c" * 40) + "\n")
        status = snapshot_status(
            Path("."),
            {
                "repository_path": ".",
                "base_commit": "c" * 40,
            },
        )
        self.assertEqual(status["status"], "match")
        self.assertTrue(status["match"])


if __name__ == "__main__":
    unittest.main()
