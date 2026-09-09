from __future__ import annotations

import asyncio
import threading
import time
import unittest


class RetrievalSchedulerTests(unittest.TestCase):
    def test_results_are_returned_in_input_order_not_completion_order(self):
        from ai_workflow.retrieval_scheduler import BoundedRetrievalScheduler, ScheduledCall

        def delayed(value: str, delay: float):
            time.sleep(delay)
            return value

        calls = [
            ScheduledCall("slow", lambda: delayed("slow", 0.06)),
            ScheduledCall("fast", lambda: delayed("fast", 0.005)),
        ]
        outcomes = asyncio.run(BoundedRetrievalScheduler(2).run(calls, deadline_seconds=1.0))
        self.assertEqual([item.label for item in outcomes], ["slow", "fast"])
        self.assertEqual([item.value for item in outcomes], ["slow", "fast"])

    def test_max_concurrency_is_enforced(self):
        from ai_workflow.retrieval_scheduler import BoundedRetrievalScheduler, ScheduledCall

        lock = threading.Lock()
        active = 0
        peak = 0

        def work():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return "ok"

        calls = [ScheduledCall(str(index), work) for index in range(8)]
        outcomes = asyncio.run(BoundedRetrievalScheduler(3).run(calls, deadline_seconds=2.0))
        self.assertEqual(peak, 3)
        self.assertTrue(all(item.error is None for item in outcomes))

    def test_global_deadline_marks_unfinished_calls_as_timed_out(self):
        from ai_workflow.retrieval_scheduler import BoundedRetrievalScheduler, ScheduledCall

        calls = [
            ScheduledCall("fast", lambda: "done"),
            ScheduledCall("slow", lambda: (time.sleep(0.3), "late")[1]),
        ]
        started = time.perf_counter()
        outcomes = asyncio.run(BoundedRetrievalScheduler(2).run(calls, deadline_seconds=0.05))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.2)
        self.assertEqual(outcomes[0].value, "done")
        self.assertTrue(outcomes[1].timed_out)
        self.assertEqual(outcomes[1].error_kind, "deadline")

    def test_callable_exception_is_isolated(self):
        from ai_workflow.retrieval_scheduler import BoundedRetrievalScheduler, ScheduledCall

        def boom():
            raise RuntimeError("boom")

        outcomes = asyncio.run(
            BoundedRetrievalScheduler(2).run(
                [ScheduledCall("bad", boom), ScheduledCall("good", lambda: 7)],
                deadline_seconds=1.0,
            )
        )
        self.assertEqual(outcomes[0].error_kind, "exception")
        self.assertIn("RuntimeError", outcomes[0].error or "")
        self.assertEqual(outcomes[1].value, 7)


if __name__ == "__main__":
    unittest.main()
