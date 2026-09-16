import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_workflow.benchmark_intervention import (
    build_seed_intervention_manifest,
    deterministic_non_gold_sample,
    run_intervention_runner,
    run_seed_interventions,
    tracked_files,
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

    def test_tracked_files_success_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (root / "a.py").write_text("x=1\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "a.py"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.assertEqual(tracked_files(root), ["a.py"])

        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            side_effect=OSError("git unavailable"),
        ):
            with self.assertRaisesRegex(ValueError, "unable to enumerate"):
                tracked_files(Path("."))

        failed = SimpleNamespace(returncode=1, stdout=b"")
        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            return_value=failed,
        ):
            with self.assertRaisesRegex(ValueError, "unable to enumerate"):
                tracked_files(Path("."))

    def test_manifest_builds_all_seed_modes_and_validates_mode(self):
        tasks = [
            {
                "task": "fix auth",
                "task_type": "edit2ripple",
                "repository_path": ".",
                "base_commit": "a" * 40,
                "gold_files": ["src/auth.py"],
                "retrieval_k": 1,
            },
            {
                "task": "no gold control",
                "repository_path": ".",
                "gold_files": [],
            },
        ]
        benchmark = {
            "cases": [
                {
                    "file_retrieval": {
                        "retrieved_files": ["src/auth.py", "src/noise.py"]
                    }
                },
                {"file_retrieval": {"retrieved_files": []}},
            ],
            "summary": {"cases": 2},
        }
        with (
            patch(
                "ai_workflow.benchmark_intervention.run_benchmark",
                return_value=benchmark,
            ),
            patch(
                "ai_workflow.benchmark_intervention.resolve_case_root",
                return_value=Path("/repo"),
            ),
            patch(
                "ai_workflow.benchmark_intervention.snapshot_status",
                return_value={"match": True},
            ),
            patch(
                "ai_workflow.benchmark_intervention.tracked_files",
                return_value=["src/auth.py", "src/noise.py", "src/other.py"],
            ),
        ):
            manifest = build_seed_intervention_manifest(
                Path("/workspace"),
                {},
                tasks,
                seed_k=2,
            )

        self.assertEqual(manifest["modes"], ["retrieval", "random_non_gold", "oracle_gold"])
        self.assertEqual(len(manifest["interventions"]), 3)
        by_mode = {
            row["seed_mode"]: row
            for row in manifest["interventions"]
        }
        self.assertEqual(by_mode["retrieval"]["seed_files"][0], "src/auth.py")
        self.assertEqual(by_mode["oracle_gold"]["seed_files"], ["src/auth.py"])
        self.assertNotIn(
            "src/auth.py",
            by_mode["random_non_gold"]["seed_files"],
        )
        self.assertEqual(manifest["benchmark_summary"], {"cases": 2})

        with self.assertRaisesRegex(ValueError, "unknown seed mode"):
            build_seed_intervention_manifest(
                Path("."),
                {},
                tasks[:1],
                modes=["unknown"],
            )

    def test_runner_validation_and_failure_statuses(self):
        intervention = {
            "task": "fix a",
            "task_type": "edit2ripple",
            "repository_path": ".",
            "base_commit": "a" * 40,
            "seed_mode": "retrieval",
            "seed_files": ["src/a.py"],
            "gold_files": ["src/a.py"],
        }

        with self.assertRaisesRegex(ValueError, "must not be empty"):
            run_intervention_runner(Path("."), intervention, [])
        with self.assertRaisesRegex(ValueError, "timeout"):
            run_intervention_runner(
                Path("."),
                intervention,
                ["runner"],
                timeout_seconds=0,
            )
        with self.assertRaisesRegex(ValueError, "output bytes"):
            run_intervention_runner(
                Path("."),
                intervention,
                ["runner"],
                max_output_bytes=0,
            )

        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            side_effect=subprocess.TimeoutExpired("runner", 1),
        ):
            result = run_intervention_runner(
                Path("."),
                intervention,
                ["runner"],
                timeout_seconds=1,
            )
        self.assertEqual(result["status"], "timeout")

        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            side_effect=OSError("missing"),
        ):
            result = run_intervention_runner(Path("."), intervention, ["runner"])
        self.assertEqual(result["status"], "launch_error")

        def fake_output_limit(*_args, **kwargs):
            kwargs["stdout"].write(b"x" * 20)
            return SimpleNamespace(returncode=0)

        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            side_effect=fake_output_limit,
        ):
            result = run_intervention_runner(
                Path("."),
                intervention,
                ["runner"],
                max_output_bytes=4,
            )
        self.assertEqual(result["status"], "output_limit")

        def fake_exit(*_args, **_kwargs):
            return SimpleNamespace(returncode=7)

        with patch(
            "ai_workflow.benchmark_intervention.subprocess.run",
            side_effect=fake_exit,
        ):
            result = run_intervention_runner(Path("."), intervention, ["runner"])
        self.assertEqual(result["status"], "exit_error")

    def test_runner_rejects_invalid_payload_shapes(self):
        intervention = {
            "task": "fix a",
            "repository_path": ".",
            "seed_mode": "retrieval",
            "seed_files": ["src/a.py"],
            "gold_files": ["src/a.py"],
        }

        def run_with_payload(payload: bytes):
            def fake_run(*_args, **kwargs):
                kwargs["stdout"].write(payload)
                return SimpleNamespace(returncode=0)

            with patch(
                "ai_workflow.benchmark_intervention.subprocess.run",
                side_effect=fake_run,
            ):
                return run_intervention_runner(
                    Path("."),
                    intervention,
                    ["runner"],
                )

        self.assertEqual(run_with_payload(b"not-json")["status"], "invalid_output")
        self.assertEqual(run_with_payload(b"[]")["status"], "invalid_output")
        self.assertEqual(
            run_with_payload(b'{"trajectory_events":{}}')["status"],
            "invalid_output",
        )

        with patch(
            "ai_workflow.benchmark_intervention.load_trajectory_events",
            side_effect=ValueError("bad event"),
        ):
            result = run_with_payload(b'{"trajectory_events":[]}')
        self.assertEqual(result["status"], "invalid_output")
        self.assertIn("bad event", result["error"])

    def test_runner_normalizes_optional_success_and_metadata(self):
        intervention = {
            "task": "fix a",
            "repository_path": ".",
            "seed_mode": "retrieval",
            "seed_files": ["src/a.py"],
            "gold_files": ["src/a.py"],
        }

        def fake_run(*_args, **kwargs):
            kwargs["stdout"].write(
                b'{"success":"yes","trajectory_events":[],"metadata":"bad"}'
            )
            return SimpleNamespace(returncode=0)

        with (
            patch(
                "ai_workflow.benchmark_intervention.subprocess.run",
                side_effect=fake_run,
            ),
            patch(
                "ai_workflow.benchmark_intervention.load_trajectory_events",
                return_value=[],
            ),
            patch(
                "ai_workflow.benchmark_intervention.trajectory_metrics",
                return_value={"seed_gold_recall": 0.0},
            ),
        ):
            result = run_intervention_runner(Path("."), intervention, ["runner"])

        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["success"])
        self.assertEqual(result["metadata"], {})

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
