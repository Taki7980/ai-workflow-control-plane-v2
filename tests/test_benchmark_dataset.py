import json
import unittest
from pathlib import Path


class BenchmarkDatasetTests(unittest.TestCase):
    def test_sample_corpus_is_broad_enough_for_regression_use(self):
        path = Path(__file__).parents[1] / "benchmarks" / "sample-tasks.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 24)
        query_types = {case.get("query_type") for case in cases}
        self.assertTrue({"exact", "semantic", "structural", "mutation", "high-risk", "mixed"}.issubset(query_types))
        self.assertTrue(all(case.get("expected_lane") for case in cases))
        self.assertTrue(all(case.get("expected_intent") for case in cases))
        self.assertTrue(all(int(case.get("retrieval_k", 0)) > 0 for case in cases))


if __name__ == "__main__":
    unittest.main()
