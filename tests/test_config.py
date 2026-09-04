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
