import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.retrieval_learning import (
    BASELINE_ARM,
    apply_learning_arm,
    choose_learning_decision,
    load_learning_records,
    prepare_learning_decision,
    record_verified_outcome,
    write_learning_decision,
)


class FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


class RetrievalLearningTests(unittest.TestCase):
    def _config(self):
        config = default_config()
        config["context"]["learning"] = {
            "mode": "explore",
            "kill_switch": False,
            "exploration_probability": 0.5,
            "allowed_risks": ["low"],
            "eligible_arms": ["adaptive_math", "bm25_rank"],
        }
        return config

    def test_low_risk_exploration_logs_exact_propensity(self):
        decision = RouteDecision(Lane.SMALL, Risk.LOW)
        selected = choose_learning_decision(
            "find payment helper",
            decision,
            "exact",
            self._config(),
            rng=FixedRng(0.9),
        )

        self.assertEqual(selected.chosen_arm, "bm25_rank")
        self.assertTrue(selected.explored)
        self.assertAlmostEqual(
            selected.arm_propensities[BASELINE_ARM],
            0.75,
        )
        self.assertAlmostEqual(
            selected.arm_propensities["bm25_rank"],
            0.25,
        )
        self.assertAlmostEqual(selected.chosen_propensity, 0.25)

    def test_high_risk_is_locked_to_baseline(self):
        decision = RouteDecision(Lane.FULL, Risk.HIGH)
        selected = choose_learning_decision(
            "change payment authorization",
            decision,
            "structural",
            self._config(),
            rng=FixedRng(0.99),
        )

        self.assertEqual(selected.chosen_arm, BASELINE_ARM)
        self.assertFalse(selected.explored)
        self.assertEqual(selected.safety_reason, "risk_locked")
        self.assertEqual(selected.arm_propensities, {BASELINE_ARM: 1.0})

    @patch.dict(
        "os.environ",
        {"AI_WORKFLOW_LEARNING_KILL_SWITCH": "1"},
        clear=False,
    )
    def test_environment_kill_switch_forces_baseline(self):
        decision = RouteDecision(Lane.SMALL, Risk.LOW)
        selected = choose_learning_decision(
            "rename helper",
            decision,
            "exact",
            self._config(),
            rng=FixedRng(0.99),
        )

        self.assertEqual(selected.chosen_arm, BASELINE_ARM)
        self.assertEqual(selected.safety_reason, "kill_switch")

    def test_explicit_empty_allowed_risks_disables_exploration(self):
        config = self._config()
        config["context"]["learning"]["allowed_risks"] = []
        decision = RouteDecision(Lane.SMALL, Risk.LOW)

        selected = choose_learning_decision(
            "rename helper",
            decision,
            "exact",
            config,
            rng=FixedRng(0.99),
        )

        self.assertEqual(selected.chosen_arm, BASELINE_ARM)
        self.assertEqual(selected.safety_reason, "risk_locked")

    @patch(
        "ai_workflow.retrieval_learning.write_learning_decision",
        side_effect=OSError("disk unavailable"),
    )
    def test_unlogged_exploration_fails_closed_to_baseline(self, _write):
        decision = RouteDecision(Lane.SMALL, Risk.LOW)

        with tempfile.TemporaryDirectory() as temp:
            selected, path = prepare_learning_decision(
                Path(temp),
                "find helper",
                decision,
                "exact",
                self._config(),
                rng=FixedRng(0.99),
            )

        self.assertEqual(selected.chosen_arm, BASELINE_ARM)
        self.assertEqual(selected.safety_reason, "decision_log_failure")
        self.assertIsNone(path)

    def test_delayed_verified_outcome_links_to_decision(self):
        config = self._config()
        config["context"]["learning"]["mode"] = "observe"
        decision = choose_learning_decision(
            "find helper",
            RouteDecision(Lane.SMALL, Risk.LOW),
            "exact",
            config,
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            record_verified_outcome(
                root,
                decision.decision_id,
                success=True,
                source="unit-test",
                reward=0.9,
                realized_cost=0.1,
            )
            rows = load_learning_records(root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_id"], decision.decision_id)
        self.assertTrue(rows[0]["outcome"]["verified"])
        self.assertEqual(rows[0]["outcome"]["reward"], 0.9)

    def test_unknown_outcome_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                record_verified_outcome(
                    Path(temp),
                    "a" * 32,
                    success=False,
                    source="unit-test",
                )

    def test_learning_arm_only_changes_ranking_experiment(self):
        config = default_config()
        changed = apply_learning_arm(config, "rrf_mmr_050")

        self.assertEqual(
            changed["context"]["experiments"]["hybrid_ranker"],
            "rrf_mmr",
        )
        self.assertEqual(
            changed["context"]["experiments"]["mmr_lambda"],
            0.5,
        )
        self.assertNotIn("experiments", config["context"])


if __name__ == "__main__":
    unittest.main()
