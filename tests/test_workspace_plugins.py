import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.retriever_plugins import configured_retrievers, run_retriever
from ai_workflow.workspace import workspace_roots


class WorkspaceTests(unittest.TestCase):
    def test_workspace_roots_resolve_relative_existing_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sibling = root / "backend"
            sibling.mkdir()
            cfg = {"workspace": {"roots": ["backend", "missing"], "max_roots": 4}}
            self.assertEqual(workspace_roots(root, cfg), [root.resolve(), sibling.resolve()])


class RetrieverPluginTests(unittest.TestCase):
    def test_plugins_are_filtered_by_intent(self):
        cfg = {"context": {"external_retrievers": [
            {"name": "semantic-extra", "command": "tool", "intents": ["semantic", "mixed"]},
            {"name": "graph-extra", "command": "graph", "intents": ["structural"]},
        ]}}
        self.assertEqual([x["name"] for x in configured_retrievers(cfg, "semantic")], ["semantic-extra"])

    def test_command_plugin_parses_json_results(self):
        spec = {"name": "custom", "command": "custom-retriever", "intents": ["all"], "timeout_seconds": 2}
        fake = type("P", (), {"returncode": 0, "stdout": json.dumps([{"text": "payment dependency", "score": 0.8, "path": "service.py"}])})()
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.retriever_plugins.subprocess.run", return_value=fake):
            items = run_retriever(Path(td), "payment", "semantic", spec, 5)
        self.assertEqual(items[0].source, "external:custom")
        self.assertEqual(items[0].metadata["path"], "service.py")
        self.assertTrue(items[0].metadata["plugin"])


if __name__ == "__main__":
    unittest.main()
