import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.models import ContextItem
from ai_workflow.retrieval_contracts import ProviderResult
from ai_workflow.semantic import semantic_context, semantic_ready


class SemanticProviderTests(unittest.TestCase):
    def test_not_ready_without_command(self):
        self.assertFalse(semantic_ready({"context": {"semantic": {"command": ""}}}))

    def test_off_mode_disables_config_and_environment_command(self):
        cfg = {"context": {"semantic": {"mode": "off", "command": "semantic-cmd", "timeout_seconds": 2}}}
        with patch.dict(os.environ, {"AI_WORKFLOW_SEMANTIC_CMD": "env-semantic"}):
            self.assertFalse(semantic_ready(cfg))

    def test_typed_provider_candidates_preserve_list_api(self):
        cfg = {"context": {"semantic": {"command": "semantic-cmd", "timeout_seconds": 2}}}
        fake = ProviderResult(
            "semantic",
            (ContextItem("semantic", "payment retry guard", 0.91, metadata={"path": "payments.py", "retriever": "semantic"}),),
            1.2,
        )
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.semantic.run_command_provider", return_value=fake):
            items = semantic_context(Path(td), "avoid duplicate charge", cfg, 5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "semantic")
        self.assertEqual(items[0].metadata["path"], "payments.py")
        self.assertEqual(items[0].metadata["retriever"], "semantic")

    def test_provider_failure_degrades_to_empty_list_for_legacy_callers(self):
        cfg = {"context": {"semantic": {"command": "semantic-cmd", "timeout_seconds": 2}}}
        fake = ProviderResult("semantic", error="invalid payload", error_kind="invalid_payload")
        with tempfile.TemporaryDirectory() as td, patch("ai_workflow.semantic.run_command_provider", return_value=fake):
            self.assertEqual(semantic_context(Path(td), "query", cfg, 5), [])


if __name__ == "__main__":
    unittest.main()
