import unittest

from ai_workflow.contextual_features import (
    DEFAULT_POLICY_FIELDS,
    FEATURE_SCHEMA_VERSION,
    build_context_features,
    context_key,
    feature_schema_descriptor,
)
from ai_workflow.models import Lane, Risk, RouteDecision


class ContextualFeatureTests(unittest.TestCase):
    def test_schema_is_stable_and_content_free(self):
        features = build_context_features(
            "find the payment helper for this request",
            RouteDecision(Lane.SMALL, Risk.LOW),
            "exact",
            changed_files_count=2,
            workspace_roots_count=3,
        )

        self.assertEqual(FEATURE_SCHEMA_VERSION, "retrieval-context-v1")
        self.assertEqual(features.lane, "small")
        self.assertEqual(features.risk, "low")
        self.assertEqual(features.intent, "exact")
        self.assertEqual(features.changed_files_bucket, "2-3")
        self.assertEqual(features.workspace_roots_bucket, "3+")
        self.assertNotIn("payment", str(features.to_dict()))

    def test_context_key_is_deterministic(self):
        features = build_context_features(
            "rename helper",
            RouteDecision(Lane.SMALL, Risk.LOW),
            "exact",
            changed_files_count=1,
        ).to_dict()

        left = context_key(features, DEFAULT_POLICY_FIELDS)
        right = context_key(features, DEFAULT_POLICY_FIELDS)

        self.assertEqual(left, right)
        self.assertIn('"intent":"exact"', left)

    def test_schema_descriptor_is_machine_readable(self):
        descriptor = feature_schema_descriptor()

        self.assertEqual(descriptor["version"], FEATURE_SCHEMA_VERSION)
        self.assertIn("intent", descriptor["fields"])


if __name__ == "__main__":
    unittest.main()
