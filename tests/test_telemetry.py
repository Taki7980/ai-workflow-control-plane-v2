import tempfile
import unittest
from pathlib import Path

from ai_workflow.telemetry import RetrievalTrace, summarize_traces, trace_enabled, write_trace


class TelemetryTests(unittest.TestCase):
    def test_answer_is_side_effect_free_by_default(self):
        cfg = {"context": {"telemetry": {"mode": "mutations"}}}
        self.assertFalse(trace_enabled(cfg, "answer"))
        self.assertTrue(trace_enabled(cfg, "small"))
        self.assertTrue(trace_enabled(cfg, "answer", explicit=True))

    def test_trace_write_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = RetrievalTrace("fix auth.py", "small", "low", "exact", budget_chars=1000, used_chars=250)
            trace.fallbacks.append("semantic unavailable")
            path = write_trace(root, trace)
            self.assertTrue((root / path).exists())
            summary = summarize_traces(root)
            self.assertEqual(summary["runs"], 1)
            self.assertEqual(summary["by_intent"]["exact"], 1)
            self.assertEqual(summary["fallback_rate"], 1.0)
            self.assertEqual(summary["mean_budget_utilization"], 0.25)


if __name__ == "__main__":
    unittest.main()
