import unittest

from ai_workflow.benchmark_policy_advisor import (
    BASELINE_PROFILE,
    build_safe_policy_advisor,
    case_utility,
)


def _case(
    task,
    *,
    f1,
    risk="low",
    task_type="code2test",
    budget=0.2,
    elapsed=100,
):
    return {
        "task": task,
        "task_type": task_type,
        "control_type": "positive",
        "risk": risk,
        "budget_utilization": budget,
        "elapsed_ms": elapsed,
        "file_retrieval": {"file_f1": f1},
    }


class BenchmarkPolicyAdvisorTests(unittest.TestCase):
    def test_case_utility_penalizes_context_and_latency(self):
        lean = _case("x", f1=0.8, budget=0.1, elapsed=50)
        heavy = _case("x", f1=0.8, budget=1.0, elapsed=1000)

        self.assertGreater(case_utility(lean), case_utility(heavy))

    def test_advisor_recommends_only_when_lower_bound_clears_margin(self):
        baseline = [
            _case(f"task-{i}", f1=0.4)
            for i in range(8)
        ]
        better = [
            _case(f"task-{i}", f1=0.8)
            for i in range(8)
        ]
        report = {
            "results": {
                BASELINE_PROFILE: {"cases": baseline},
                "bm25_rank": {"cases": better},
            }
        }

        result = build_safe_policy_advisor(
            report,
            minimum_samples=4,
            confidence=0.9,
            resamples=500,
            seed=2,
            safety_margin=0.05,
        )

        recommendation = result["recommendations"]["code2test"]
        self.assertEqual(
            recommendation["recommended_profile"],
            "bm25_rank",
        )
        self.assertEqual(
            recommendation["status"],
            "advisory_candidate",
        )
        self.assertFalse(result["safety"]["runtime_override_enabled"])

    def test_high_risk_cases_do_not_train_candidate_policy(self):
        baseline = [
            _case(
                f"high-{i}",
                f1=0.1,
                risk="high",
            )
            for i in range(6)
        ] + [
            _case(
                f"low-{i}",
                f1=0.5,
                risk="low",
            )
            for i in range(3)
        ]
        candidate = [
            _case(
                f"high-{i}",
                f1=1.0,
                risk="high",
            )
            for i in range(6)
        ] + [
            _case(
                f"low-{i}",
                f1=0.5,
                risk="low",
            )
            for i in range(3)
        ]
        report = {
            "results": {
                BASELINE_PROFILE: {"cases": baseline},
                "rrf_only": {"cases": candidate},
            }
        }

        result = build_safe_policy_advisor(
            report,
            minimum_samples=2,
            resamples=200,
            seed=4,
        )

        recommendation = result["recommendations"]["code2test"]
        self.assertEqual(
            recommendation["recommended_profile"],
            BASELINE_PROFILE,
        )
        self.assertIn("high", result["safety"]["locked_risks"])

    def test_weak_evidence_retains_baseline(self):
        baseline = [
            _case(f"task-{i}", f1=0.5)
            for i in range(4)
        ]
        candidate = [
            _case(f"task-{i}", f1=0.5)
            for i in range(4)
        ]
        report = {
            "results": {
                BASELINE_PROFILE: {"cases": baseline},
                "rrf_only": {"cases": candidate},
            }
        }

        result = build_safe_policy_advisor(
            report,
            minimum_samples=4,
            resamples=200,
            safety_margin=0.0,
        )

        self.assertEqual(
            result["recommendations"]["code2test"][
                "recommended_profile"
            ],
            BASELINE_PROFILE,
        )


if __name__ == "__main__":
    unittest.main()
