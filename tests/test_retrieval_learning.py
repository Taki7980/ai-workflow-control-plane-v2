import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.outcome_verification import TRUSTED_OUTCOME_SOURCES_ENV
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

    @staticmethod
    def _evidence_digest(label: str = "unit-test-evidence") -> str:
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _decision(self):
        config = self._config()
        config["context"]["learning"]["mode"] = "observe"
        return choose_learning_decision(
            "find helper",
            RouteDecision(Lane.SMALL, Risk.LOW),
            "exact",
            config,
        )

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

    def test_delayed_verified_outcome_links_to_decision_with_evidence(self):
        decision = self._decision()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            record_verified_outcome(
                root,
                decision.decision_id,
                success=True,
                source="local:test-suite",
                verifier_identity="unittest:RetrievalLearningTests",
                evidence_digest=self._evidence_digest(),
                reward=0.9,
                realized_cost=0.1,
            )
            rows = load_learning_records(root)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_id"], decision.decision_id)
        self.assertTrue(rows[0]["outcome"]["verified"])
        self.assertEqual(rows[0]["outcome"]["reward"], 0.9)
        self.assertEqual(
            rows[0]["outcome"]["verifier_identity"],
            "unittest:RetrievalLearningTests",
        )
        self.assertEqual(
            rows[0]["outcome"]["evidence_digest"],
            self._evidence_digest(),
        )
        self.assertIsNotNone(
            rows[0]["outcome"]["verification_delay_seconds"]
        )

    def test_unknown_outcome_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                record_verified_outcome(
                    Path(temp),
                    "a" * 32,
                    success=False,
                    source="local:test-suite",
                    verifier_identity="unittest",
                    evidence_digest=self._evidence_digest(),
                )

    def test_untrusted_outcome_source_is_rejected(self):
        decision = self._decision()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            with self.assertRaisesRegex(ValueError, "not trusted"):
                record_verified_outcome(
                    root,
                    decision.decision_id,
                    success=True,
                    source="repository:claims-success",
                    verifier_identity="repo-config",
                    evidence_digest=self._evidence_digest(),
                )

    def test_outcome_requires_verifier_identity_and_sha256_evidence(self):
        decision = self._decision()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            with self.assertRaisesRegex(ValueError, "verifier_identity"):
                record_verified_outcome(
                    root,
                    decision.decision_id,
                    success=True,
                    source="local:test-suite",
                    verifier_identity="",
                    evidence_digest=self._evidence_digest(),
                )
            with self.assertRaisesRegex(ValueError, "sha256"):
                record_verified_outcome(
                    root,
                    decision.decision_id,
                    success=True,
                    source="local:test-suite",
                    verifier_identity="unittest",
                    evidence_digest="result-passed",
                )

    def test_reward_is_bounded_to_verified_schema(self):
        decision = self._decision()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            for reward in (-0.01, 1.01, float("inf")):
                with self.subTest(reward=reward):
                    with self.assertRaisesRegex(ValueError, "between 0.0 and 1.0"):
                        record_verified_outcome(
                            root,
                            decision.decision_id,
                            success=True,
                            source="local:test-suite",
                            verifier_identity="unittest",
                            evidence_digest=self._evidence_digest(),
                            reward=reward,
                        )

    def test_runtime_policy_can_add_trusted_verifier_without_repo_config(self):
        decision = self._decision()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_learning_decision(root, decision)
            with patch.dict(
                os.environ,
                {TRUSTED_OUTCOME_SOURCES_ENV: "ci:custom-verifier"},
                clear=False,
            ):
                record_verified_outcome(
                    root,
                    decision.decision_id,
                    success=True,
                    source="ci:custom-verifier",
                    verifier_identity="build-123/check-456",
                    evidence_digest=self._evidence_digest("custom-ci"),
                )
            rows = load_learning_records(root)
        self.assertEqual(rows[0]["outcome"]["source"], "ci:custom-verifier")

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
