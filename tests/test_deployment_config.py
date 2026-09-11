import unittest

from ai_workflow.config import default_config, validate_config


class DeploymentConfigTests(unittest.TestCase):
    def test_default_deployment_is_disabled(self):
        config = default_config()

        self.assertFalse(config["context"]["deployment"]["enabled"])
        validate_config(config)

    def test_existing_v2_config_without_deployment_remains_valid(self):
        config = default_config()
        config["context"].pop("deployment")

        validate_config(config)

    def test_deployment_state_path_cannot_escape_project_root(self):
        config = default_config()
        config["context"]["deployment"]["state_path"] = "../active.json"

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_enabled_deployment_requires_automatic_rollback(self):
        config = default_config()
        config["context"]["deployment"]["enabled"] = True
        config["context"]["deployment"]["auto_rollback"] = False

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_default_production_store_is_disabled(self):
        config = default_config()

        self.assertFalse(config["context"]["production"]["enabled"])
        validate_config(config)

    def test_production_store_path_cannot_escape_project_root(self):
        config = default_config()
        config["context"]["production"]["sqlite_path"] = "../events.sqlite3"

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_incident_bundle_flag_must_be_boolean(self):
        config = default_config()
        config["context"]["deployment"]["incident_bundles"] = "yes"

        with self.assertRaises(ValueError):
            validate_config(config)

    def test_deployment_requires_nonempty_signing_key_env_name(self):
        config = default_config()
        config["context"]["deployment"]["signing_key_env"] = ""

        with self.assertRaises(ValueError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
