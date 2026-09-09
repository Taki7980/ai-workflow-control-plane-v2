import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.indexer import build_indexes, incremental_indexes


class IndexerRouteAndStateTests(unittest.TestCase):
    def test_spring_mapping_routes_do_not_depend_on_generic_capture_groups(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "src" / "UserController.java"
            source.parent.mkdir(parents=True)
            source.write_text(
                """
class UserController {
    @GetMapping("/users")
    public String list() { return "ok"; }

    @PostMapping(path = "/users")
    public String create() { return "ok"; }

    @RequestMapping("/health")
    public String health() { return "ok"; }
}
""",
                encoding="utf-8",
            )

            stats = build_indexes(root)
            endpoint_path = root / "ai-workspace" / "generated" / "endpoint-index.jsonl"
            endpoints = [json.loads(line) for line in endpoint_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(stats["endpoints"], 3)
            self.assertIn(("GET", "/users"), {(row["method"], row["path"]) for row in endpoints})
            self.assertEqual([row["path"] for row in endpoints].count("/users"), 2)
            self.assertIn(("REQUEST", "/health"), {(row["method"], row["path"]) for row in endpoints})

    def test_incremental_state_write_preserves_valid_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "service.py").write_text("def ok():\n    return True\n", encoding="utf-8")
            build_indexes(root)
            state_path = root / "ai-workspace" / "generated" / "index-state.json"
            before = state_path.read_text(encoding="utf-8")
            self.assertIn('"files"', before)
            incremental_indexes(root)
            after = state_path.read_text(encoding="utf-8")
            self.assertIn('"files"', after)
            self.assertEqual(json.loads(before)["files"], json.loads(after)["files"])


if __name__ == "__main__":
    unittest.main()
