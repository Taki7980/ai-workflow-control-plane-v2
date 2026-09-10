import unittest

from ai_workflow.config import default_config, validate_config


class RetrievalLearningConfigTests(unittest.TestCase):
    def test_default_learning_is_off(self):
        config = default_config()

        self.assertEqual(config["context"]["learning"]["mode"], "off")
        validate_config(config)

    def test_existing_v2_config_without_learning_remains_valid(self):
        config = default_config()
        config["context"].pop("learning")

        validate_config(config)

    def test_medium_or_high_risk_exploration_cannot_be_configured(self):
        config = default_config()
        config["context"]["learning"]["allowed_risks"] = ["medium"]

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_safety_affecting_stage3_profiles_cannot_be_exploration_arms(self):
        config = default_config()
        config["context"]["learning"]["eligible_arms"] = [
            "adaptive_math",
            "selector_off",
        ]

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_baseline_arm_is_required(self):
        config = default_config()
        config["context"]["learning"]["eligible_arms"] = ["bm25_rank"]

        with self.assertRaises(ValueError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
