import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.models import ContextItem
from ai_workflow.provider_runner import CommandProviderSpec
from ai_workflow.retrieval_contracts import ProviderResult
from ai_workflow.semantic import semantic_context, semantic_ready


class SemanticProviderTests(unittest.TestCase):
    def test_not_ready_without_provider_id(self):
        self.assertFalse(semantic_ready({"context": {"semantic": {"provider_id": ""}}}))

    def test_repository_command_is_not_ready_without_explicit_unsafe_compatibility(self):
        cfg = {"context": {"semantic": {"command": "semantic-cmd", "timeout_seconds": 2}}}
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS", None)
            self.assertFalse(semantic_ready(cfg))

    def test_off_mode_disables_config_and_environment_provider(self):
        cfg = {"context": {"semantic": {"mode": "off", "provider_id": "semantic-local", "timeout_seconds": 2}}}
        with patch.dict(os.environ, {"AI_WORKFLOW_SEMANTIC_PROVIDER_ID": "env-semantic"}):
            self.assertFalse(semantic_ready(cfg))

    def test_typed_provider_candidates_preserve_list_api(self):
        cfg = {"context": {"semantic": {"provider_id": "semantic-local", "timeout_seconds": 2}}}
        fake = ProviderResult(
            "semantic",
            (ContextItem("semantic", "payment retry guard", 0.91, metadata={"path": "payments.py", "retriever": "semantic"}),),
            1.2,
        )
        trusted = CommandProviderSpec(
            "semantic",
            (sys.executable, "-c", "print('unused')"),
            timeout_seconds=2,
            executable_trust="trusted_registry_digest",
        )
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.semantic.resolve_project_provider",
            return_value=trusted,
        ), patch("ai_workflow.semantic.run_command_provider", return_value=fake):
            items = semantic_context(Path(td), "avoid duplicate charge", cfg, 5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "semantic")
        self.assertEqual(items[0].metadata["path"], "payments.py")
        self.assertEqual(items[0].metadata["retriever"], "semantic")

    def test_provider_failure_degrades_to_empty_list_for_legacy_callers(self):
        cfg = {"context": {"semantic": {"provider_id": "semantic-local", "timeout_seconds": 2}}}
        fake = ProviderResult("semantic", error="invalid payload", error_kind="invalid_payload")
        trusted = CommandProviderSpec(
            "semantic",
            (sys.executable, "-c", "print('unused')"),
            timeout_seconds=2,
            executable_trust="trusted_registry_digest",
        )
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.semantic.resolve_project_provider",
            return_value=trusted,
        ), patch("ai_workflow.semantic.run_command_provider", return_value=fake):
            self.assertEqual(semantic_context(Path(td), "query", cfg, 5), [])


if __name__ == "__main__":
    unittest.main()
