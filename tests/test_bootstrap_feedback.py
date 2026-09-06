import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.bootstrap import bootstrap
from ai_workflow.config import load_config
from ai_workflow.telemetry import RetrievalTrace, policy_recommendations, write_trace


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_minimal_control_plane_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = bootstrap(root, "Demo")
            self.assertEqual(result["status"], "bootstrapped")
            self.assertTrue((root / "AGENTS.md").exists())
            self.assertTrue((root / "ai-workspace/config/control-plane.json").exists())
            self.assertEqual(load_config(root)["version"], 2)
            with self.assertRaises(FileExistsError):
                bootstrap(root, "DemoAgain")


class FeedbackTests(unittest.TestCase):
    def test_feedback_is_advisory_and_requires_enough_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(5):
                trace = RetrievalTrace(f"task {i}", "small", "low", "semantic", budget_chars=1000, used_chars=200)
                trace.sufficiency = {"score": 0.95, "sufficient": True}
                write_trace(root, trace)
            low = policy_recommendations(root, minimum_runs=20)
            self.assertEqual(low["recommendations"], [])
            for i in range(20):
                trace = RetrievalTrace(f"more {i}", "small", "low", "semantic", budget_chars=1000, used_chars=200)
                trace.sufficiency = {"score": 0.95, "sufficient": True}
                write_trace(root, trace)
            result = policy_recommendations(root, minimum_runs=20)
            self.assertTrue(any(r["signal"] == "consistently_high_sufficiency" for r in result["recommendations"]))
            self.assertIn("advisory", result["note"])


if __name__ == "__main__":
    unittest.main()
