from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


class ProviderBoundaryContractTests(unittest.TestCase):
    def _module(self, name: str):
        spec = importlib.util.find_spec(name)
        self.assertIsNotNone(spec, f"expected new module {name}")
        return __import__(name, fromlist=["*"])

    def _provider_script(self, root: Path, body: str) -> Path:
        script = root / "provider.py"
        script.write_text(body, encoding="utf-8")
        return script

    def test_typed_retrieval_contracts_are_immutable_and_preserve_context_items(self):
        contracts = self._module("ai_workflow.retrieval_contracts")
        from ai_workflow.models import ContextItem

        request = contracts.RetrievalRequest(
            query="find payment handler",
            root=Path("/repo"),
            limit=3,
            intent="exact",
            timeout_seconds=2.0,
        )
        item = ContextItem("semantic", "payment handler", 0.9)
        result = contracts.ProviderResult("semantic", (item,), 12.5)

        self.assertEqual(request.query, "find payment handler")
        self.assertEqual(result.items, (item,))
        with self.assertRaises(Exception):
            request.query = "mutated"

    def test_workspace_path_policy_rejects_absolute_parent_and_symlink_escape(self):
        paths = self._module("ai_workflow.path_policy")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "safe.txt").write_text("ok", encoding="utf-8")

            self.assertEqual(paths.resolve_within_root(root, "safe.txt"), (root / "safe.txt").resolve())
            with self.assertRaises(paths.PathOutsideWorkspace):
                paths.resolve_within_root(root, "../outside/secret.txt")
            with self.assertRaises(paths.PathOutsideWorkspace):
                paths.resolve_within_root(root, outside.resolve())

            link = root / "escape"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")
            with self.assertRaises(paths.PathOutsideWorkspace):
                paths.resolve_within_root(root, "escape/secret.txt")

    def test_provider_environment_is_allowlisted_and_explicit_secrets_are_opt_in(self):
        runner = self._module("ai_workflow.provider_runner")
        old = os.environ.get("AI_WORKFLOW_TEST_SECRET")
        os.environ["AI_WORKFLOW_TEST_SECRET"] = "do-not-inherit"
        try:
            env = runner.build_provider_env()
            self.assertNotIn("AI_WORKFLOW_TEST_SECRET", env)
            explicit = runner.build_provider_env(["AI_WORKFLOW_TEST_SECRET"])
            self.assertEqual(explicit["AI_WORKFLOW_TEST_SECRET"], "do-not-inherit")
        finally:
            if old is None:
                os.environ.pop("AI_WORKFLOW_TEST_SECRET", None)
            else:
                os.environ["AI_WORKFLOW_TEST_SECRET"] = old

    def test_command_runner_returns_success_with_bounded_typed_result(self):
        runner = self._module("ai_workflow.provider_runner")
        contracts = self._module("ai_workflow.retrieval_contracts")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = self._provider_script(
                root,
                "import json,sys\n"
                "req=json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'items':[{'text':'hit '+req['query'],'score':0.8}]}))\n",
            )
            spec = runner.CommandProviderSpec(
                name="test",
                command=(sys.executable, str(script)),
                timeout_seconds=2,
                max_output_bytes=4096,
            )
            request = contracts.RetrievalRequest("needle", root, 2, "semantic", 2)
            result = runner.run_command_provider(spec, request, source="external:test")

            self.assertIsNone(result.error)
            self.assertEqual(result.provider, "test")
            self.assertEqual([item.text for item in result.items], ["hit needle"])

    def test_command_runner_stops_output_above_limit(self):
        runner = self._module("ai_workflow.provider_runner")
        contracts = self._module("ai_workflow.retrieval_contracts")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = self._provider_script(root, "import sys\nsys.stdin.read()\nsys.stdout.write('x'*200000)\n")
            spec = runner.CommandProviderSpec(
                name="noisy",
                command=(sys.executable, str(script)),
                timeout_seconds=2,
                max_output_bytes=1024,
            )
            result = runner.run_command_provider(
                spec,
                contracts.RetrievalRequest("q", root, 1, "semantic", 2),
                source="external:noisy",
            )
            self.assertEqual(result.error_kind, "output_limit")
            self.assertTrue(result.output_limited)
            self.assertEqual(result.items, ())

    def test_command_runner_exposes_timeout_exit_and_invalid_payload_failures(self):
        runner = self._module("ai_workflow.provider_runner")
        contracts = self._module("ai_workflow.retrieval_contracts")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = contracts.RetrievalRequest("q", root, 1, "semantic", 1)

            cases = [
                ("timeout", "import sys,time\nsys.stdin.read()\ntime.sleep(2)\n", "timeout", 0.1),
                ("exit", "import sys\nsys.stdin.read()\nsys.exit(7)\n", "exit", 1),
                ("bad", "import sys\nsys.stdin.read()\nprint('not-json')\n", "invalid_payload", 1),
            ]
            for name, body, expected, timeout in cases:
                script = self._provider_script(root, body)
                result = runner.run_command_provider(
                    runner.CommandProviderSpec(
                        name=name,
                        command=(sys.executable, str(script)),
                        timeout_seconds=timeout,
                        max_output_bytes=4096,
                    ),
                    request,
                    source=f"external:{name}",
                )
                self.assertEqual(result.error_kind, expected, name)

    def test_provider_paths_are_confined_without_dropping_safe_text_evidence(self):
        runner = self._module("ai_workflow.provider_runner")
        contracts = self._module("ai_workflow.retrieval_contracts")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = self._provider_script(
                root,
                "import json,sys\nsys.stdin.read()\n"
                "print(json.dumps({'items':[{'text':'useful evidence','score':1,'path':'../secret.txt'}]}))\n",
            )
            result = runner.run_command_provider(
                runner.CommandProviderSpec("paths", (sys.executable, str(script)), 1, 4096),
                contracts.RetrievalRequest("q", root, 2, "semantic", 1),
                source="external:paths",
            )
            self.assertIsNone(result.error)
            self.assertEqual(result.items[0].text, "useful evidence")
            self.assertNotIn("path", result.items[0].metadata)
            self.assertTrue(result.items[0].metadata.get("path_rejected"))

    def test_command_provider_spec_normalizes_string_commands_and_intents(self):
        runner = self._module("ai_workflow.provider_runner")
        spec = runner.command_provider_spec(
            {"name": "docs", "command": f'"{sys.executable}" provider.py', "intents": ["exact", "semantic"]},
            default_name="external",
        )
        self.assertEqual(spec.name, "docs")
        self.assertEqual(spec.command[0], sys.executable)
        self.assertEqual(spec.intents, ("exact", "semantic"))

    def test_malformed_provider_score_is_coerced_instead_of_crashing(self):
        runner = self._module("ai_workflow.provider_runner")
        contracts = self._module("ai_workflow.retrieval_contracts")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script = self._provider_script(
                root,
                "import json,sys\nsys.stdin.read()\n"
                "print(json.dumps({'items':[{'text':'still usable','score':'not-a-number'}]}))\n",
            )
            result = runner.run_command_provider(
                runner.CommandProviderSpec("score", (sys.executable, str(script)), 1, 4096),
                contracts.RetrievalRequest("q", root, 1, "semantic", 1),
                source="external:score",
            )
            self.assertIsNone(result.error)
            self.assertEqual(result.items[0].score, 0.0)

    def test_memory_rejects_file_references_outside_workspace(self):
        from ai_workflow.memory import add_memory

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            root.mkdir()
            (base / "secret.txt").write_text("secret", encoding="utf-8")
            with self.assertRaises(ValueError):
                add_memory(root, "decision", "security", "safe", files=["../secret.txt"])
            self.assertFalse((root / "ai-workspace" / "memory" / "memory.jsonl").exists())

    def test_workspace_fingerprint_marks_escaped_changed_file_as_rejected(self):
        from ai_workflow.workspace_state import workspace_fingerprint

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "repo"
            root.mkdir()
            (base / "outside.py").write_text("secret = True\n", encoding="utf-8")
            snapshot = workspace_fingerprint(root, ["../outside.py"])
            self.assertEqual(snapshot["changed_files"], [{"path": "../outside.py", "state": "rejected", "sha256": None}])

    def test_provider_config_defaults_and_safety_fields_validate(self):
        from ai_workflow.config import default_config, validate_config

        cfg = default_config()
        validate_config(cfg)
        self.assertEqual(cfg["context"]["semantic"]["max_output_bytes"], 8 * 1024 * 1024)
        self.assertEqual(cfg["context"]["semantic"]["env_allowlist"], [])

        cfg["context"]["external_retrievers"] = [{
            "name": "docs",
            "command": [sys.executable, "provider.py"],
            "intents": ["all"],
            "timeout_seconds": 2,
            "max_output_bytes": 4096,
            "env_allowlist": ["DOCS_TOKEN"],
        }]
        validate_config(cfg)

        cfg["context"]["external_retrievers"][0]["max_output_bytes"] = 0
        with self.assertRaises(ValueError):
            validate_config(cfg)


if __name__ == "__main__":
    unittest.main()
