import tempfile
import unittest
from pathlib import Path

from ai_workflow.contextual_features import (
    FEATURE_SCHEMA_VERSION,
    context_key,
)
from ai_workflow.contextual_policy import (
    build_contextual_policy_report,
    target_action_for_row,
)
from ai_workflow.io_utils import atomic_write_json
from ai_workflow.retrieval_learning import BASELINE_ARM, learning_root


FEATURES = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}


class ContextualPolicyTests(unittest.TestCase):
    def _write_event(
        self,
        root: Path,
        index: int,
        arm: str,
        reward: float,
        *,
        risk: str = "low",
    ) -> None:
        decision_id = f"{index:032x}"
        base = learning_root(root)
        features = dict(FEATURES)
        features["risk"] = risk
        atomic_write_json(
            base / "decisions" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "chosen_arm": arm,
                "arm_propensities": {
                    BASELINE_ARM: 0.5,
                    "bm25_rank": 0.5,
                },
                "risk": risk,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "context_features": features,
            },
        )
        atomic_write_json(
            base / "outcomes" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "verified": True,
                "reward": reward,
                "realized_cost": 0.1,
                "recorded_at": (
                    f"2026-09-11T00:{index % 60:02d}:00+00:00"
                ),
            },
        )

    def test_context_policy_uses_independent_holdout_dr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, 121):
                arm = "bm25_rank" if index % 2 else BASELINE_ARM
                reward = 1.0 if arm == "bm25_rank" else 0.0
                self._write_event(root, index, arm, reward)

            report = build_contextual_policy_report(
                root,
                context_fields=["intent"],
                development_fraction=0.65,
                minimum_context_events=6,
                minimum_direct_exposures=2,
                minimum_holdout_events=10,
                minimum_effective_sample_size=5,
                minimum_model_validation_events=5,
                confidence=0.9,
                resamples=300,
                seed=17,
            )

        key = context_key(FEATURES, ("intent",))
        self.assertEqual(report["development_policy"][key], "bm25_rank")
        self.assertGreater(report["development_events"], 0)
        self.assertGreater(report["holdout_events"], 0)
        self.assertEqual(
            report["reward_model_cross_validation"]["rmse"],
            0.0,
        )
        evaluation = report["holdout_doubly_robust_evaluation"]
        self.assertEqual(
            evaluation["reward_delta_vs_baseline"]["mean"],
            1.0,
        )
        self.assertTrue(report["promotion"]["eligible_for_shadow"])
        self.assertFalse(
            report["promotion"]["automatic_runtime_promotion"]
        )

    def test_high_risk_target_is_always_baseline(self):
        features = dict(FEATURES)
        features["risk"] = "high"
        row = {
            "risk": "high",
            "context_features": features,
            "arm_propensities": {
                BASELINE_ARM: 1.0,
            },
        }
        key = context_key(features, ("intent",))

        chosen = target_action_for_row(
            row,
            {key: "bm25_rank"},
            ("intent",),
        )

        self.assertEqual(chosen, BASELINE_ARM)


if __name__ == "__main__":
    unittest.main()
