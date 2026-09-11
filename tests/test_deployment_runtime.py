import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.contextual_features import FEATURE_SCHEMA_VERSION, context_key
from ai_workflow.deployment_runtime import resolve_runtime_deployment
from ai_workflow.deployment_state import (
    create_deployment_state,
    load_deployment_state,
    transition_deployment_state,
    write_new_deployment_state,
)
from ai_workflow.io_utils import atomic_write_json
from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.policy_manifest import create_policy_manifest
from ai_workflow.retrieval_learning import (
    BASELINE_ARM,
    choose_learning_decision,
    learning_root,
)


FEATURES = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}


def build_manifest(key):
    context = context_key(FEATURES, ("intent",))
    return create_policy_manifest(
        {
            "scope": "contextual-retrieval-policy-development",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "context_fields": ["intent"],
            "development_policy": {context: "bm25_rank"},
            "evidence_cutoff": "2026-09-10T00:00:00+00:00",
            "source_decision_sha256": "b" * 64,
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


def shadow(manifest):
    return {
        "policy_id": manifest["policy_id"],
        "evidence_cutoff": manifest["evidence_cutoff"],
        "manifest_verification": {"valid": True},
        "execution": {"policy_received_runtime_traffic": False},
        "shadow_gate": {
            "eligible_for_manual_promotion_review": True,
        },
    }


def deployment_config():
    config = default_config()
    config["context"]["deployment"]["enabled"] = True
    config["context"]["deployment"]["state_path"] = "active.json"
    config["context"]["deployment"]["signing_key_env"] = "STAGE7_KEY"
    config["context"]["deployment"]["auto_rollback"] = True
    config["context"]["learning"]["mode"] = "explore"
    config["context"]["learning"]["exploration_probability"] = 1.0
    return config


class DeploymentRuntimeTests(unittest.TestCase):
    def _state(self, root, key, *, minimum_monitor_outcomes=20):
        manifest = build_manifest(key)
        state = create_deployment_state(
            root,
            manifest,
            shadow(manifest),
            key,
            approved_by="release-owner",
            minimum_monitor_outcomes=minimum_monitor_outcomes,
            minimum_drift_samples=10000,
        )
        state = transition_deployment_state(
            state,
            key,
            to_stage="canary_1",
            actor="release-owner",
        )
        write_new_deployment_state(root / "active.json", state, key)
        return state

    @patch.dict("os.environ", {"STAGE7_KEY": "secret-key"}, clear=False)
    @patch(
        "ai_workflow.deployment_runtime._assignment_fraction",
        return_value=(0.001, "nonce-candidate"),
    )
    def test_candidate_assignment_logs_exact_canary_probability(
        self,
        _fraction,
    ):
        key = b"secret-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = self._state(root, key)
            assignment = resolve_runtime_deployment(
                root,
                "find exact payment helper now",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                deployment_config(),
                changed_files_count=1,
            )

        self.assertEqual(assignment["chosen_arm"], "bm25_rank")
        self.assertEqual(
            assignment["arm_propensities"],
            {BASELINE_ARM: 0.99, "bm25_rank": 0.01},
        )
        self.assertEqual(
            assignment["deployment"]["state_generation"],
            state["generation"],
        )
        self.assertEqual(
            assignment["deployment"]["assignment"],
            "candidate",
        )

    @patch.dict("os.environ", {"STAGE7_KEY": "secret-key"}, clear=False)
    @patch(
        "ai_workflow.deployment_runtime._assignment_fraction",
        return_value=(0.9, "nonce-control"),
    )
    def test_control_assignment_preempts_stage5_exploration(
        self,
        _fraction,
    ):
        key = b"secret-key"
        config = deployment_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._state(root, key)
            assignment = resolve_runtime_deployment(
                root,
                "find exact payment helper now",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
                changed_files_count=1,
            )
            learning = choose_learning_decision(
                "find exact payment helper now",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
                changed_files_count=1,
                deployment_assignment=assignment,
            )

        self.assertEqual(learning.mode, "canary")
        self.assertEqual(learning.chosen_arm, BASELINE_ARM)
        self.assertAlmostEqual(learning.chosen_propensity, 0.99)
        self.assertEqual(
            learning.deployment["assignment"],
            "control",
        )

    @patch.dict("os.environ", {"STAGE7_KEY": "secret-key"}, clear=False)
    def test_high_risk_is_baseline_locked_before_canary(self):
        key = b"secret-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._state(root, key)
            assignment = resolve_runtime_deployment(
                root,
                "change production payment authorization",
                RouteDecision(Lane.FULL, Risk.HIGH),
                "structural",
                deployment_config(),
            )

        self.assertEqual(assignment["chosen_arm"], BASELINE_ARM)
        self.assertEqual(
            assignment["safety_reason"],
            "deployment_risk_locked",
        )
        self.assertEqual(
            assignment["arm_propensities"],
            {BASELINE_ARM: 1.0},
        )

    @patch.dict(
        "os.environ",
        {
            "STAGE7_KEY": "secret-key",
            "AI_WORKFLOW_LEARNING_KILL_SWITCH": "1",
        },
        clear=False,
    )
    def test_global_learning_kill_switch_stops_canary(self):
        key = b"secret-key"
        config = deployment_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._state(root, key)
            assignment = resolve_runtime_deployment(
                root,
                "find exact payment helper now",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
                changed_files_count=1,
            )

        self.assertEqual(assignment["chosen_arm"], BASELINE_ARM)
        self.assertEqual(
            assignment["safety_reason"],
            "deployment_global_kill_switch",
        )

    def test_missing_signing_key_fails_closed_even_if_learning_explores(self):
        config = deployment_config()
        with tempfile.TemporaryDirectory() as temp:
            assignment = resolve_runtime_deployment(
                Path(temp),
                "find helper",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
            )

        self.assertEqual(assignment["chosen_arm"], BASELINE_ARM)
        self.assertEqual(
            assignment["safety_reason"],
            "deployment_signing_key_missing",
        )

    @patch.dict("os.environ", {"STAGE7_KEY": "secret-key"}, clear=False)
    def test_live_failure_guardrail_auto_rolls_back_state(self):
        key = b"secret-key"
        config = deployment_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = self._state(
                root,
                key,
                minimum_monitor_outcomes=1,
            )
            base = learning_root(root)
            decision_id = "f" * 32
            atomic_write_json(
                base / "decisions" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "created_at": "2026-09-11T00:00:00+00:00",
                    "chosen_arm": "bm25_rank",
                    "arm_propensities": {
                        BASELINE_ARM: 0.99,
                        "bm25_rank": 0.01,
                    },
                    "risk": "low",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "context_features": dict(FEATURES),
                    "deployment": {
                        "policy_id": state["policy_id"],
                        "state_generation": state["generation"],
                        "stage": "canary_1",
                        "assignment": "candidate",
                        "candidate_probability": 0.01,
                    },
                },
            )
            atomic_write_json(
                base / "outcomes" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "verified": True,
                    "success": False,
                    "reward": 0.0,
                    "realized_cost": 0.1,
                    "recorded_at": "2026-09-11T00:01:00+00:00",
                },
            )

            assignment = resolve_runtime_deployment(
                root,
                "find exact payment helper now",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
                changed_files_count=1,
            )
            current = load_deployment_state(root / "active.json")
            incidents = list(
                (
                    root
                    / "ai-workspace"
                    / "generated"
                    / "learning"
                    / "deployment"
                    / "incidents"
                ).glob("*.json")
            )

        self.assertEqual(assignment["chosen_arm"], BASELINE_ARM)
        self.assertEqual(
            assignment["safety_reason"],
            "deployment_auto_rollback",
        )
        self.assertEqual(current["stage"], "rolled_back")
        self.assertEqual(current["traffic_fraction"], 0.0)
        self.assertTrue(current["rollback"]["automatic"])
        self.assertEqual(len(incidents), 1)


if __name__ == "__main__":
    unittest.main()
