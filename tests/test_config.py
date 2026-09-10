import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.config import DEFAULT_RELATIVE, load_config


class ConfigValidationTests(unittest.TestCase):
    def write_config(self, root: Path, data: dict) -> None:
        path = root / DEFAULT_RELATIVE
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_missing_required_sections_fail_at_load_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_config(root, {"version": 2})

            with self.assertRaisesRegex(ValueError, "missing required section: budgets"):
                load_config(root)

    def test_invalid_source_share_fails_at_load_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = Path(__file__).parents[1] / DEFAULT_RELATIVE
            data = json.loads(source.read_text(encoding="utf-8"))
            data["context"]["source_shares"]["lightweight"] = 1.5
            self.write_config(root, data)

            with self.assertRaisesRegex(ValueError, "source share"):
                load_config(root)


    def test_stage4_graph_defaults(self):
        from ai_workflow.config import default_config

        self.assertEqual(
            default_config()["workspace"]["graph"],
            {
                "enabled": True,
                "max_hops": 2,
                "max_nodes": 24,
                "max_edges": 40,
                "max_context_chars": 3000,
                "min_edge_confidence": 0.8,
                "build_on_demand": True,
            },
        )

    def test_stage4_graph_config_rejects_invalid_values(self):
        from ai_workflow.config import default_config, validate_config

        invalid = (
            ("max_hops", 0),
            ("max_hops", 4),
            ("max_nodes", 0),
            ("max_nodes", 101),
            ("max_edges", 0),
            ("max_edges", 201),
            ("max_context_chars", 255),
            ("max_context_chars", 12001),
            ("min_edge_confidence", -0.01),
            ("min_edge_confidence", 1.01),
            ("enabled", "yes"),
            ("build_on_demand", "yes"),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                config = default_config()
                config["workspace"]["graph"][key] = value
                with self.assertRaises(ValueError):
                    validate_config(config)


    def test_stage4_graph_defaults_are_backfilled_for_existing_v2_config(self):
        source = Path(__file__).parents[1] / DEFAULT_RELATIVE
        data = json.loads(source.read_text(encoding="utf-8"))
        data["workspace"].pop("graph", None)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_config(root, data)
            loaded = load_config(root)

        self.assertEqual(loaded["workspace"]["graph"]["max_hops"], 2)
        self.assertTrue(loaded["workspace"]["graph"]["enabled"])
