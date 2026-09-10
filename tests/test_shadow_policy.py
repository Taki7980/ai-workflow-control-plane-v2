import tempfile
import unittest
from pathlib import Path

from ai_workflow.contextual_features import (
    FEATURE_SCHEMA_VERSION,
    context_key,
)
from ai_workflow.io_utils import atomic_write_json
from ai_workflow.policy_manifest import create_policy_manifest
from ai_workflow.retrieval_learning import BASELINE_ARM, learning_root
from ai_workflow.shadow_policy import (
    anytime_hoeffding_sequence,
    evaluate_shadow_policy,
)


FEATURES = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}


def report_for_shadow():
    key = context_key(FEATURES, ("intent",))
    return {
        "scope": "contextual-retrieval-policy-development",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "context_fields": ["intent"],
        "development_policy": {key: "bm25_rank"},
        "evidence_cutoff": "2026-09-10T00:00:00+00:00",
        "source_decision_sha256": "b" * 64,
        "development_events": 50,
        "holdout_events": 20,
        "reward_model": {
            "global_mean": 0.0,
            "arm_means": {
                BASELINE_ARM: -1.0,
                "bm25_rank": 1.0,
            },
            "context_arm_means": {
                key: {
                    BASELINE_ARM: -1.0,
                    "bm25_rank": 1.0,
                }
            },
        },
        "cost_model": {
            "global_mean": 0.1,
            "arm_means": {
                BASELINE_ARM: 0.1,
                "bm25_rank": 0.1,
            },
            "context_arm_means": {
                key: {
                    BASELINE_ARM: 0.1,
                    "bm25_rank": 0.1,
                }
            },
        },
        "holdout_doubly_robust_evaluation": {
            "reward_delta_vs_baseline": {
                "ci_low": 0.5,
            }
        },
        "promotion": {
            "eligible_for_shadow": True,
        },
    }


class ShadowPolicyTests(unittest.TestCase):
    def _write_event(
        self,
        root: Path,
        index: int,
        *,
        chosen: str,
        reward: float,
        candidate_probability: float = 0.5,
    ) -> None:
        decision_id = f"{index:032x}"
        base = learning_root(root)
        baseline_probability = 1.0 - candidate_probability
        atomic_write_json(
            base / "decisions" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "chosen_arm": chosen,
                "arm_propensities": {
                    BASELINE_ARM: baseline_probability,
                    "bm25_rank": candidate_probability,
                },
                "risk": "low",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "context_features": dict(FEATURES),
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
                    f"2026-09-11T01:{index % 60:02d}:"
                    f"{index % 59:02d}+00:00"
                ),
            },
        )

    def test_shadow_gate_uses_only_post_cutoff_evidence(self):
        key = b"shadow-signing-key"
        manifest = create_policy_manifest(report_for_shadow(), key)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(1, 65):
                chosen = (
                    "bm25_rank"
                    if index % 2
                    else BASELINE_ARM
                )
                reward = 1.0 if chosen == "bm25_rank" else -1.0
                self._write_event(
                    root,
                    index,
                    chosen=chosen,
                    reward=reward,
                )

            result = evaluate_shadow_policy(
                root,
                manifest,
                key,
                confidence=0.9,
                reward_min=-1.0,
                reward_max=1.0,
                max_importance_weight=2.0,
                minimum_new_events=20,
                safety_margin=0.0,
                max_realized_cost=0.5,
                bootstrap_resamples=200,
                bootstrap_seed=9,
            )

        self.assertEqual(result["post_cutoff_events"], 64)
        self.assertEqual(result["unsupported_target_events"], 0)
        self.assertTrue(
            result["shadow_gate"][
                "eligible_for_manual_promotion_review"
            ]
        )
        self.assertFalse(
            result["execution"]["policy_received_runtime_traffic"]
        )
        final = result["sequential_reward_confidence"]["final"]
        self.assertGreater(final["lower"], 0.0)

    def test_zero_target_propensity_blocks_shadow_gate(self):
        key = b"shadow-signing-key"
        manifest = create_policy_manifest(report_for_shadow(), key)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_event(
                root,
                1,
                chosen=BASELINE_ARM,
                reward=-1.0,
                candidate_probability=0.0,
            )
            result = evaluate_shadow_policy(
                root,
                manifest,
                key,
                confidence=0.9,
                reward_min=-1.0,
                reward_max=1.0,
                max_importance_weight=2.0,
                minimum_new_events=1,
            )

        self.assertEqual(result["unsupported_target_events"], 1)
        self.assertFalse(
            result["shadow_gate"][
                "eligible_for_manual_promotion_review"
            ]
        )
        self.assertIn(
            "target_policy_support_violation",
            result["shadow_gate"]["blockers"],
        )

    def test_anytime_sequence_reports_sparse_checkpoints(self):
        sequence = anytime_hoeffding_sequence(
            [0.5] * 17,
            confidence=0.9,
            absolute_bound=1.0,
        )

        self.assertTrue(sequence["anytime_valid"])
        self.assertEqual(sequence["final"]["n"], 17)
        self.assertEqual(
            [point["n"] for point in sequence["checkpoints"]],
            [1, 2, 4, 8, 16, 17],
        )


if __name__ == "__main__":
    unittest.main()
