from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.config import DEFAULT_RELATIVE, default_config


class TypedConfigTests(unittest.TestCase):
    def test_recursive_immutability_and_mapping_compatibility(self):
        from ai_workflow.typed_config import ControlPlaneConfig

        raw = default_config()
        typed = ControlPlaneConfig.from_dict(raw)
        self.assertEqual(typed["version"], 2)
        self.assertEqual(typed.get("workspace")["max_roots"], 4)
        self.assertEqual(typed.context["max_results_per_source"], 6)
        with self.assertRaises(TypeError):
            typed.context["max_results_per_source"] = 99
        with self.assertRaises(TypeError):
            typed["workspace"]["roots"][0] = "x"

    def test_unknown_fields_survive_round_trip(self):
        from ai_workflow.typed_config import ControlPlaneConfig

        raw = default_config()
        raw["custom_extension"] = {"enabled": True, "nested": ["a", {"x": 1}]}
        typed = ControlPlaneConfig.from_dict(raw)
        self.assertEqual(typed.to_dict(), raw)

    def test_to_dict_is_detached_from_typed_state(self):
        from ai_workflow.typed_config import ControlPlaneConfig

        typed = ControlPlaneConfig.from_dict(default_config())
        mutable = typed.to_dict()
        mutable["workspace"]["roots"].append("other")
        self.assertEqual(tuple(typed.workspace["roots"]), ())

    def test_missing_version_and_v1_migrate_to_v2_preserving_unknown_keys(self):
        from ai_workflow.config import migrate_config

        for source in ({"workspace": {"roots": ["backend"]}, "custom": 7}, {"version": 1, "workspace": {"roots": ["backend"]}, "custom": 7}):
            migrated = migrate_config(source)
            self.assertEqual(migrated["version"], 2)
            self.assertEqual(migrated["workspace"]["roots"], ["backend"])
            self.assertEqual(migrated["workspace"]["max_roots"], 4)
            self.assertEqual(migrated["custom"], 7)
            self.assertIn("budgets", migrated)

    def test_future_version_is_refused(self):
        from ai_workflow.config import migrate_config

        raw = default_config()
        raw["version"] = 3
        with self.assertRaisesRegex(ValueError, "newer than supported"):
            migrate_config(raw)

    def test_load_typed_and_legacy_load_config_are_isolated(self):
        from ai_workflow.config import load_config, load_typed_config

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / DEFAULT_RELATIVE
            path.parent.mkdir(parents=True)
            raw = default_config()
            raw["extension"] = {"mode": "custom"}
            path.write_text(json.dumps(raw), encoding="utf-8")

            typed = load_typed_config(root)
            legacy = load_config(root)
            legacy["workspace"]["roots"].append("mutated")
            self.assertEqual(tuple(typed.workspace["roots"]), ())
            self.assertEqual(typed["extension"]["mode"], "custom")


if __name__ == "__main__":
    unittest.main()
