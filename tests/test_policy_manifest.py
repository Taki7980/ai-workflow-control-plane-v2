import copy
import unittest

from ai_workflow.contextual_features import (
    FEATURE_SCHEMA_VERSION,
    context_key,
)
from ai_workflow.policy_manifest import (
    MANIFEST_SCHEMA_VERSION,
    create_policy_manifest,
    verify_policy_manifest,
)
from ai_workflow.retrieval_learning import BASELINE_ARM


FEATURES = {
    "lane": "small",
    "risk": "low",
    "intent": "exact",
    "query_length_bucket": "5-8",
    "changed_files_bucket": "1",
    "workspace_roots_bucket": "1",
}


def sample_report():
    key = context_key(FEATURES, ("intent",))
    return {
        "scope": "contextual-retrieval-policy-development",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "context_fields": ["intent"],
        "development_policy": {key: "bm25_rank"},
        "evidence_cutoff": "2026-09-10T00:00:00+00:00",
        "source_decision_sha256": "a" * 64,
        "development_events": 40,
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
                "ci_low": 0.2,
            }
        },
        "promotion": {
            "eligible_for_shadow": True,
        },
    }


class PolicyManifestTests(unittest.TestCase):
    def test_signed_manifest_verifies_and_stays_shadow_only(self):
        key = b"stage-6-test-key"
        manifest = create_policy_manifest(sample_report(), key)
        result = verify_policy_manifest(manifest, key)

        self.assertTrue(result["valid"])
        self.assertEqual(
            manifest["schema_version"],
            MANIFEST_SCHEMA_VERSION,
        )
        self.assertEqual(manifest["status"], "shadow_only")
        self.assertFalse(manifest["automatic_runtime_activation"])
        self.assertEqual(
            manifest["rollback"]["target_arm"],
            BASELINE_ARM,
        )

    def test_tampering_breaks_manifest_verification(self):
        key = b"stage-6-test-key"
        manifest = create_policy_manifest(sample_report(), key)
        tampered = copy.deepcopy(manifest)
        context = next(iter(tampered["policy"]))
        tampered["policy"][context] = "rrf_only"

        result = verify_policy_manifest(tampered, key)

        self.assertFalse(result["valid"])
        self.assertIn("signature_mismatch", result["errors"])

    def test_ineligible_report_cannot_be_signed(self):
        report = sample_report()
        report["promotion"]["eligible_for_shadow"] = False

        with self.assertRaises(ValueError):
            create_policy_manifest(report, b"key")


if __name__ == "__main__":
    unittest.main()
