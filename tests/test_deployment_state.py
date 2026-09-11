import tempfile
import unittest
from pathlib import Path

from ai_workflow.contextual_features import FEATURE_SCHEMA_VERSION, context_key
from ai_workflow.deployment_state import (
    create_deployment_state,
    load_deployment_state,
    transition_deployment_state,
    update_deployment_state_file,
    verify_deployment_state,
    write_new_deployment_state,
)
from ai_workflow.policy_manifest import create_policy_manifest
from ai_workflow.retrieval_learning import BASELINE_ARM


FEATURES = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}


def signed_manifest(key: bytes):
    context = context_key(FEATURES, ("intent",))
    report = {
        "scope": "contextual-retrieval-policy-development",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "context_fields": ["intent"],
        "development_policy": {context: "bm25_rank"},
        "evidence_cutoff": "2026-09-10T00:00:00+00:00",
        "source_decision_sha256": "a" * 64,
        "development_events": 50,
        "holdout_events": 25,
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
    }
    return create_policy_manifest(report, key)


def passing_shadow(manifest):
    return {
        "policy_id": manifest["policy_id"],
        "evidence_cutoff": manifest["evidence_cutoff"],
        "manifest_verification": {"valid": True},
        "execution": {"policy_received_runtime_traffic": False},
        "shadow_gate": {
            "eligible_for_manual_promotion_review": True,
        },
    }


class DeploymentStateTests(unittest.TestCase):
    def test_create_starts_approved_with_zero_traffic(self):
        key = b"stage7-key"
        manifest = signed_manifest(key)

        with tempfile.TemporaryDirectory() as temp:
            state = create_deployment_state(
                Path(temp),
                manifest,
                passing_shadow(manifest),
                key,
                approved_by="release-owner",
            )

        result = verify_deployment_state(state, key)
        self.assertTrue(result["valid"])
        self.assertEqual(state["stage"], "approved")
        self.assertEqual(state["traffic_fraction"], 0.0)
        self.assertEqual(state["generation"], 1)
        self.assertFalse(state["automatic_runtime_activation"])

    def test_forward_transitions_are_sequential_and_evidence_gated(self):
        key = b"stage7-key"
        manifest = signed_manifest(key)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = create_deployment_state(
                root,
                manifest,
                passing_shadow(manifest),
                key,
                approved_by="release-owner",
            )
            one = transition_deployment_state(
                state,
                key,
                to_stage="canary_1",
                actor="release-owner",
            )

            with self.assertRaises(ValueError):
                transition_deployment_state(
                    one,
                    key,
                    to_stage="canary_5",
                    actor="release-owner",
                )

            guardrail = {
                "policy_id": manifest["policy_id"],
                "stage": "canary_1",
                "state_generation": 2,
                "gate": {"safe_to_advance": True},
            }
            five = transition_deployment_state(
                one,
                key,
                to_stage="canary_5",
                actor="release-owner",
                guardrail_report=guardrail,
            )

        self.assertEqual(one["traffic_fraction"], 0.01)
        self.assertEqual(five["traffic_fraction"], 0.05)
        self.assertEqual(five["generation"], 3)

    def test_tampering_invalidates_signed_state(self):
        key = b"stage7-key"
        manifest = signed_manifest(key)
        with tempfile.TemporaryDirectory() as temp:
            state = create_deployment_state(
                Path(temp),
                manifest,
                passing_shadow(manifest),
                key,
                approved_by="release-owner",
            )
        state["traffic_fraction"] = 0.5

        result = verify_deployment_state(state, key)

        self.assertFalse(result["valid"])
        self.assertIn("signature_mismatch", result["errors"])
        self.assertIn("traffic_fraction_mismatch", result["errors"])

    def test_stale_generation_cannot_overwrite_state(self):
        key = b"stage7-key"
        manifest = signed_manifest(key)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "active.json"
            state = create_deployment_state(
                root,
                manifest,
                passing_shadow(manifest),
                key,
                approved_by="release-owner",
            )
            write_new_deployment_state(path, state, key)
            update_deployment_state_file(
                path,
                key,
                to_stage="canary_1",
                actor="release-owner",
                expected_generation=1,
            )
            with self.assertRaises(ValueError):
                update_deployment_state_file(
                    path,
                    key,
                    to_stage="canary_5",
                    actor="release-owner",
                    expected_generation=1,
                    guardrail_report={
                        "policy_id": manifest["policy_id"],
                        "stage": "canary_1",
                        "state_generation": 2,
                        "gate": {"safe_to_advance": True},
                    },
                )
            current = load_deployment_state(path)

        self.assertEqual(current["stage"], "canary_1")
        self.assertEqual(current["generation"], 2)

    def test_rollback_is_terminal_for_same_state(self):
        key = b"stage7-key"
        manifest = signed_manifest(key)
        with tempfile.TemporaryDirectory() as temp:
            state = create_deployment_state(
                Path(temp),
                manifest,
                passing_shadow(manifest),
                key,
                approved_by="release-owner",
            )
            one = transition_deployment_state(
                state,
                key,
                to_stage="canary_1",
                actor="release-owner",
            )
            rolled = transition_deployment_state(
                one,
                key,
                to_stage="rolled_back",
                actor="release-owner",
                reason="manual safety stop",
            )
            with self.assertRaises(ValueError):
                transition_deployment_state(
                    rolled,
                    key,
                    to_stage="canary_5",
                    actor="release-owner",
                )

        self.assertEqual(rolled["traffic_fraction"], 0.0)
        self.assertEqual(
            rolled["rollback"]["target_arm"],
            BASELINE_ARM,
        )


if __name__ == "__main__":
    unittest.main()
