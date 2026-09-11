import tempfile
import unittest
from pathlib import Path

from ai_workflow.contextual_features import FEATURE_SCHEMA_VERSION, context_key
from ai_workflow.deployment_guardrails import evaluate_live_guardrails
from ai_workflow.deployment_state import (
    create_deployment_state,
    transition_deployment_state,
)
from ai_workflow.io_utils import atomic_write_json
from ai_workflow.policy_manifest import create_policy_manifest
from ai_workflow.retrieval_learning import BASELINE_ARM, learning_root


EXACT = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}
SEMANTIC = {
    **EXACT,
    "intent": "semantic",
}


def manifest_and_shadow(key):
    context = context_key(EXACT, ("intent",))
    manifest = create_policy_manifest(
        {
            "scope": "contextual-retrieval-policy-development",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "context_fields": ["intent"],
            "development_policy": {context: "bm25_rank"},
            "evidence_cutoff": "2026-09-10T00:00:00+00:00",
            "source_decision_sha256": "c" * 64,
            "development_events": 50,
            "holdout_events": 20,
            "reward_model": {
                "global_mean": 0.5,
                "arm_means": {BASELINE_ARM: 0.4, "bm25_rank": 0.8},
                "context_arm_means": {
                    context: {BASELINE_ARM: 0.4, "bm25_rank": 0.8}
                },
            },
            "cost_model": {
                "global_mean": 0.1,
                "arm_means": {BASELINE_ARM: 0.1, "bm25_rank": 0.1},
                "context_arm_means": {
                    context: {BASELINE_ARM: 0.1, "bm25_rank": 0.1}
                },
            },
            "holdout_doubly_robust_evaluation": {
                "reward_delta_vs_baseline": {"ci_low": 0.1}
            },
            "promotion": {"eligible_for_shadow": True},
        },
        key,
    )
    shadow = {
        "policy_id": manifest["policy_id"],
        "evidence_cutoff": manifest["evidence_cutoff"],
        "manifest_verification": {"valid": True},
        "execution": {"policy_received_runtime_traffic": False},
        "shadow_gate": {
            "eligible_for_manual_promotion_review": True,
        },
    }
    return manifest, shadow


class DeploymentGuardrailTests(unittest.TestCase):
    def _write_row(
        self,
        root,
        state,
        index,
        *,
        assignment,
        success=True,
        reward=1.0,
        features=EXACT,
    ):
        decision_id = f"{index:032x}"
        probability = 0.01
        chosen = "bm25_rank" if assignment == "candidate" else BASELINE_ARM
        base = learning_root(root)
        atomic_write_json(
            base / "decisions" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "created_at": f"2026-09-11T00:{index % 60:02d}:00+00:00",
                "chosen_arm": chosen,
                "arm_propensities": {
                    BASELINE_ARM: 0.99,
                    "bm25_rank": 0.01,
                },
                "risk": "low",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "context_features": dict(features),
                "deployment": {
                    "policy_id": state["policy_id"],
                    "state_generation": state["generation"],
                    "stage": "canary_1",
                    "assignment": assignment,
                    "candidate_probability": probability,
                },
            },
        )
        atomic_write_json(
            base / "outcomes" / f"{decision_id}.json",
            {
                "decision_id": decision_id,
                "verified": True,
                "success": success,
                "reward": reward,
                "realized_cost": 0.1,
                "recorded_at": f"2026-09-11T01:{index % 60:02d}:00+00:00",
            },
        )

    def _state(self, root, key, **kwargs):
        manifest, shadow = manifest_and_shadow(key)
        state = create_deployment_state(
            root,
            manifest,
            shadow,
            key,
            approved_by="release-owner",
            **kwargs,
        )
        return transition_deployment_state(
            state,
            key,
            to_stage="canary_1",
            actor="release-owner",
        )

    def test_healthy_candidate_outcomes_allow_manual_advance(self):
        key = b"guardrail-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = self._state(
                root,
                key,
                minimum_monitor_outcomes=2,
                minimum_drift_samples=10000,
            )
            self._write_row(root, state, 1, assignment="candidate")
            self._write_row(root, state, 2, assignment="candidate")
            for index in range(3, 23):
                self._write_row(
                    root,
                    state,
                    index,
                    assignment="control",
                    reward=0.5,
                )

            report = evaluate_live_guardrails(root, state, key)

        self.assertFalse(report["gate"]["rollback_required"])
        self.assertTrue(report["gate"]["safe_to_advance"])
        self.assertEqual(report["exposure"]["candidate_failures"], 0)

    def test_failure_rate_triggers_rollback(self):
        key = b"guardrail-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = self._state(
                root,
                key,
                minimum_monitor_outcomes=2,
                max_failure_rate=0.25,
                minimum_drift_samples=10000,
            )
            self._write_row(
                root,
                state,
                1,
                assignment="candidate",
                success=False,
                reward=0.0,
            )
            self._write_row(
                root,
                state,
                2,
                assignment="candidate",
                success=False,
                reward=0.0,
            )

            report = evaluate_live_guardrails(root, state, key)

        self.assertTrue(report["gate"]["rollback_required"])
        self.assertIn(
            "candidate_failure_rate_regression",
            report["gate"]["rollback_blockers"],
        )

    def test_context_drift_and_unknown_context_trigger_rollback(self):
        key = b"guardrail-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = learning_root(root)
            for index in range(1, 5):
                decision_id = f"{1000 + index:032x}"
                atomic_write_json(
                    base / "decisions" / f"{decision_id}.json",
                    {
                        "decision_id": decision_id,
                        "risk": "low",
                        "feature_schema_version": FEATURE_SCHEMA_VERSION,
                        "context_features": dict(EXACT),
                    },
                )
            state = self._state(
                root,
                key,
                minimum_monitor_outcomes=100,
                minimum_drift_samples=2,
                max_context_tv_distance=0.20,
                max_unknown_context_rate=0.20,
            )
            self._write_row(
                root,
                state,
                1,
                assignment="control",
                features=SEMANTIC,
            )
            self._write_row(
                root,
                state,
                2,
                assignment="control",
                features=SEMANTIC,
            )

            report = evaluate_live_guardrails(root, state, key)

        self.assertTrue(report["gate"]["rollback_required"])
        self.assertIn(
            "context_distribution_drift",
            report["gate"]["rollback_blockers"],
        )
        self.assertIn(
            "unknown_context_rate_exceeded",
            report["gate"]["rollback_blockers"],
        )

    def test_exposure_budget_is_cumulative_across_stage(self):
        key = b"guardrail-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = self._state(
                root,
                key,
                minimum_monitor_outcomes=10000,
                minimum_drift_samples=10000,
            )
            for index in range(1, 102):
                self._write_row(
                    root,
                    state,
                    index,
                    assignment="candidate",
                )

            report = evaluate_live_guardrails(root, state, key)

        self.assertTrue(report["gate"]["rollback_required"])
        self.assertIn(
            "candidate_exposure_budget_exhausted",
            report["gate"]["rollback_blockers"],
        )


if __name__ == "__main__":
    unittest.main()
