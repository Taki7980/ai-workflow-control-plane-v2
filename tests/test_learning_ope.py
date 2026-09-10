import tempfile
import unittest
from pathlib import Path

from ai_workflow.io_utils import atomic_write_json
from ai_workflow.learning_ope import evaluate_learning_policies
from ai_workflow.retrieval_learning import BASELINE_ARM, learning_root


class LearningOpeTests(unittest.TestCase):
    def _write_event(
        self,
        root,
        index,
        chosen,
        reward,
        cost,
        *,
        candidate_probability=0.5,
    ):
        decision_id = f"{index:032x}"
        propensities = {
            BASELINE_ARM: 1.0 - candidate_probability,
            "bm25_rank": candidate_probability,
        }
        base = learning_root(root)
        atomic_write_json(
            base / "decisions" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "chosen_arm": chosen,
                "arm_propensities": propensities,
                "risk": "low",
                "mode": "explore",
            },
        )
        atomic_write_json(
            base / "outcomes" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "verified": True,
                "reward": reward,
                "realized_cost": cost,
            },
        )

    def test_snips_promotes_candidate_with_strong_supported_gain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, 21):
                if index % 2:
                    self._write_event(
                        root,
                        index,
                        "bm25_rank",
                        1.0,
                        0.2,
                    )
                else:
                    self._write_event(
                        root,
                        index,
                        BASELINE_ARM,
                        0.2,
                        0.2,
                    )

            result = evaluate_learning_policies(
                root,
                arms=["bm25_rank"],
                confidence=0.9,
                resamples=500,
                seed=7,
                minimum_effective_sample_size=5,
                minimum_direct_exposures=5,
                safety_margin=0.1,
                max_realized_cost=1.0,
            )

        candidate = result["evaluations"]["bm25_rank"]
        self.assertEqual(candidate["direct_target_exposures"], 10)
        self.assertAlmostEqual(candidate["snips_reward"], 1.0)
        self.assertGreaterEqual(candidate["effective_sample_size"], 9.9)
        self.assertTrue(candidate["promotion_eligible"])
        self.assertEqual(
            result["promotion"]["recommended_arm"],
            "bm25_rank",
        )

    def test_realized_cost_cap_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, 13):
                if index % 2:
                    self._write_event(
                        root,
                        index,
                        "bm25_rank",
                        1.0,
                        2.0,
                    )
                else:
                    self._write_event(
                        root,
                        index,
                        BASELINE_ARM,
                        0.1,
                        0.1,
                    )

            result = evaluate_learning_policies(
                root,
                arms=["bm25_rank"],
                confidence=0.9,
                resamples=300,
                minimum_effective_sample_size=3,
                minimum_direct_exposures=3,
                max_realized_cost=1.0,
            )

        candidate = result["evaluations"]["bm25_rank"]
        self.assertFalse(candidate["promotion_eligible"])
        self.assertIn(
            "realized_cost_constraint_not_met",
            candidate["promotion_blockers"],
        )
        self.assertEqual(
            result["promotion"]["recommended_arm"],
            BASELINE_ARM,
        )

    def test_insufficient_overlap_retains_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, 11):
                decision_id = f"{index:032x}"
                base = learning_root(root)
                atomic_write_json(
                    base / "decisions" / f"{decision_id}.json",
                    {
                        "decision_id": decision_id,
                        "chosen_arm": BASELINE_ARM,
                        "arm_propensities": {BASELINE_ARM: 1.0},
                        "risk": "high",
                        "mode": "explore",
                    },
                )
                atomic_write_json(
                    base / "outcomes" / f"{decision_id}.json",
                    {
                        "decision_id": decision_id,
                        "verified": True,
                        "reward": 0.5,
                        "realized_cost": 0.1,
                    },
                )

            result = evaluate_learning_policies(
                root,
                arms=["bm25_rank"],
                resamples=100,
                minimum_effective_sample_size=2,
                minimum_direct_exposures=1,
            )

        candidate = result["evaluations"]["bm25_rank"]
        self.assertEqual(candidate["direct_target_exposures"], 0)
        self.assertFalse(candidate["promotion_eligible"])
        self.assertIn(
            "insufficient_direct_target_exposures",
            candidate["promotion_blockers"],
        )
        self.assertEqual(
            result["promotion"]["recommended_arm"],
            BASELINE_ARM,
        )

    def test_unverified_outcomes_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decision_id = "f" * 32
            base = learning_root(root)
            atomic_write_json(
                base / "decisions" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "chosen_arm": BASELINE_ARM,
                    "arm_propensities": {BASELINE_ARM: 1.0},
                },
            )
            atomic_write_json(
                base / "outcomes" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "verified": False,
                    "reward": 1.0,
                    "realized_cost": 0.0,
                },
            )

            result = evaluate_learning_policies(
                root,
                arms=[BASELINE_ARM],
                resamples=50,
            )

        self.assertEqual(result["logged_verified_events"], 0)


if __name__ == "__main__":
    unittest.main()
