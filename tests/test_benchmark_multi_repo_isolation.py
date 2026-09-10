import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.benchmark import run_benchmark
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem


_DIAGNOSTICS = {
    "retrieval_intent": "exact",
    "sufficiency": {"sufficient": True, "score": 1.0},
    "evidence_state": "sufficient",
    "selector": {"mode": "test"},
    "workspace_state": {"fingerprint": "fixture"},
    "orchestration": {"complexity_score": 0.0},
    "fallbacks": [],
}


class BenchmarkMultiRepoIsolationTests(unittest.TestCase):
    @patch("ai_workflow.benchmark.gather_detailed")
    def test_case_repository_path_becomes_only_retrieval_root(self, gather):
        gather.return_value = (
            [ContextItem("targeted_source", "src/service.py:1: class Service")],
            _DIAGNOSTICS,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo_a = root / "repo-a"
            repo_b = root / "repo-b"
            repo_a.mkdir()
            repo_b.mkdir()

            config = default_config()
            config["workspace"]["roots"] = ["repo-b"]
            config["workspace"]["max_roots"] = 4

            result = run_benchmark(
                root,
                config,
                [
                    {
                        "task": "Where is Service?",
                        "repository_path": "repo-a",
                        "gold_files": ["src/service.py"],
                        "retrieval_k": 5,
                    }
                ],
            )

        args = gather.call_args.args
        self.assertEqual(args[0], repo_a.resolve())
        self.assertEqual(args[4]["workspace"]["roots"], [])
        self.assertEqual(args[4]["workspace"]["max_roots"], 1)
        self.assertEqual(result["cases"][0]["repository_path"], "repo-a")
        self.assertEqual(
            result["cases"][0]["file_retrieval"]["recall_at_k"],
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
