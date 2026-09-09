import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.models import ContextItem
from ai_workflow.retrieval_contracts import ProviderResult
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

    def test_typed_provider_candidates_preserve_legacy_list_api(self):
        spec = {"name": "custom", "command": "custom-retriever", "intents": ["all"], "timeout_seconds": 2}
        fake = ProviderResult(
            "custom",
            (ContextItem(
                "external:custom",
                "payment dependency",
                0.8,
                metadata={"path": "service.py", "plugin": True, "retriever": "custom"},
            ),),
            1.5,
        )
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.retriever_plugins.run_command_provider", return_value=fake):
            items = run_retriever(Path(td), "payment", "semantic", spec, 5)
        self.assertEqual(items[0].source, "external:custom")
        self.assertEqual(items[0].metadata["path"], "service.py")
        self.assertTrue(items[0].metadata["plugin"])

    def test_argv_commands_are_accepted(self):
        cfg = {"context": {"external_retrievers": [
            {"name": "argv", "command": ["python", "provider.py"], "intents": ["all"]},
        ]}}
        self.assertEqual([x["name"] for x in configured_retrievers(cfg, "mixed")], ["argv"])


if __name__ == "__main__":
    unittest.main()
