import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_workflow.cli import build_parser
from ai_workflow.config import DEFAULT_RELATIVE


class CliStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def template(self):
        config = self.root / DEFAULT_RELATIVE
        config.parent.mkdir(parents=True)
        config.write_bytes((Path(__file__).resolve().parents[1] / DEFAULT_RELATIVE).read_bytes())
        agents = self.root / "ai-workspace/agents/AGENTS.md"
        agents.parent.mkdir(parents=True, exist_ok=True)
        agents.write_text("# {{PROJECT_NAME}}\n", encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def run_cli_text(self, *arguments):
        args = build_parser().parse_args(["--root", str(self.root), *arguments])
        with redirect_stdout(io.StringIO()) as output:
            args.func(args)
        return output.getvalue()

    def run_cli(self, *arguments):
        return json.loads(self.run_cli_text(*arguments))

    def test_setup_defaults_project_name_and_prints_next_step(self):
        text = self.run_cli_text("setup")
        self.assertIn("AI Workflow ready", text)
        self.assertIn(self.root.name, text)
        self.assertIn('ai-workflow brief "your task" --format prompt', text)
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / ".ai").exists())
        self.assertTrue((self.root / "ai-workspace/agents/AGENTS.md").is_file())
        self.assertTrue((self.root / DEFAULT_RELATIVE).is_file())
        self.assertTrue((self.root / "ai-workspace/config/repositories.json").is_file())
        self.assertTrue((self.root / "ai-workspace/state/PROJECT").is_file())
        self.assertTrue((self.root / "ai-workspace/generated/index-state.json").is_file())

    def test_setup_is_safe_to_rerun_and_preserves_existing_agents(self):
        (self.root / "AGENTS.md").write_text("# Existing project rules\n", encoding="utf-8")
        self.run_cli_text("setup", "--project-name", "Example")
        text = self.run_cli_text("setup", "--project-name", "Renamed")
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), "# Existing project rules\n")
        self.assertIn("Preserved:", text)
        self.assertIn("AGENTS.md", text)

    def test_setup_json_output_is_machine_readable(self):
        packet = json.loads(self.run_cli_text("setup", "--project-name", "Example", "--json"))
        self.assertEqual(packet["status"], "ready")
        self.assertEqual(packet["project"], "Example")
        self.assertEqual(packet["root"], str(self.root.resolve()))
        self.assertIn("next", packet)

    def test_init_rejects_incomplete_template_without_writes(self):
        for missing in ("fresh", "config", "agents"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory)
                if missing != "fresh":
                    self.template()
                    target = DEFAULT_RELATIVE if missing == "config" else Path("ai-workspace/agents/AGENTS.md")
                    (self.root / target).unlink()
                before = self.snapshot()
                with self.assertRaisesRegex(SystemExit, "template|setup"):
                    self.run_cli("init", "--project-name", "Example")
                self.assertEqual(before, self.snapshot())

    def test_init_rejects_invalid_config_without_writes(self):
        self.template()
        (self.root / DEFAULT_RELATIVE).write_text("{}", encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.run_cli("init", "--project-name", "Example")
        self.assertEqual(before, self.snapshot())

    def test_init_valid_template(self):
        self.template()
        packet = self.run_cli("init", "--project-name", "Example")
        self.assertEqual(packet["status"], "initialized")
        self.assertEqual((self.root / "ai-workspace/agents/AGENTS.md").read_text(), "# Example\n")
        self.assertEqual((self.root / "ai-workspace/state/PROJECT").read_text().strip(), ".")
        self.assertFalse((self.root / ".ai/PROJECT").exists())
        self.assertTrue((self.root / "ai-workspace/generated/index-state.json").is_file())

    def test_answer_brief_does_not_create_state(self):
        self.template()
        before = self.snapshot()
        packet = self.run_cli("brief", "Explain this function", "--write-handoff")
        self.assertEqual(packet["lane"], "answer")
        self.assertEqual(before, self.snapshot())

    def test_answer_brief_preserves_existing_state(self):
        self.template()
        for path in ("ai-workspace/generated/last-brief.json", "ai-workspace/handoff/HANDOFF.md"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("existing state\n", encoding="utf-8")
        before = self.snapshot()
        self.run_cli("brief", "Explain this function", "--write-handoff")
        self.assertEqual(before, self.snapshot())

    def test_mutation_brief_creates_snapshot_and_handoff(self):
        self.template()
        packet = self.run_cli("brief", "Fix typo in README", "--write-handoff")
        self.assertNotEqual(packet["lane"], "answer")
        self.assertTrue((self.root / "ai-workspace/handoff/HANDOFF.md").is_file())
        self.assertEqual(packet["handoff_written"], "ai-workspace/handoff/HANDOFF.md")
        self.assertEqual(json.loads((self.root / "ai-workspace/generated/last-brief.json").read_text()), packet)

    def test_stage3_cli_workspace_metadata(self):
        self.template()
        packet = self.run_cli("context", "Explain this function")
        self.assertIn("lane", packet)
        self.assertIn("risk", packet)
        self.assertIn("budget", packet)
        self.assertIn("retrieval", packet)
        self.assertIn("items", packet)
        orchestration = packet["retrieval"]["workspace_orchestration"]
        budget = orchestration["budget"]
        self.assertLessEqual(budget["allocated_context_chars"], budget["parent_context_chars"])
        self.assertLessEqual(budget["used_context_chars"], budget["parent_context_chars"])

    def test_stage3_cli_multi_repo_metadata_and_prompt_are_portable(self):
        self.template()
        from ai_workflow.models import ContextItem
        from ai_workflow.workspace_retrieval import WorkspaceRetrievalResult

        primary = {
            "retrieval_intent": "mixed",
            "evidence_state": "sufficient",
            "sufficiency": {"sufficient": True, "score": 1.0},
            "fallbacks": [],
            "orchestration": {"agent_slots": 1, "superpowers_skills": [], "crg_plan": []},
            "workspace_state": {"fingerprint": "repo-fp"},
        }
        diagnostics = {
            "workspace_fingerprint": "workspace-fp",
            "repository_count": 3,
            "repositories_searched": ["repo-backend", "repo-frontend"],
            "repositories_skipped": ["repo-docs"],
            "changed_files_detected": ["backend/payments.py"],
            "selection": [
                {"repository_id": "repo-backend", "repository_path": "backend", "rank": 1, "score": 20.0, "selected": True, "reasons": ["changed_file"]},
                {"repository_id": "repo-frontend", "repository_path": "frontend", "rank": 2, "score": 12.0, "selected": True, "reasons": ["identity_match"]},
                {"repository_id": "repo-docs", "repository_path": "docs", "rank": 3, "score": 0.0, "selected": False, "reasons": ["no_relevant_signal"]},
            ],
            "repository_results": {},
            "budget": {
                "parent_context_chars": 1000,
                "allocated_context_chars": 1000,
                "used_context_chars": 120,
                "raw_repository_used_context_chars": 120,
            },
            "scheduler": {"max_workers": 2, "deadline_seconds": 12, "deadline_exceeded": False},
            "primary_retrieval": primary,
        }
        result = WorkspaceRetrievalResult(
            (
                ContextItem(
                    "targeted_source",
                    "payments.py:1 ProcessPayment",
                    1.0,
                    False,
                    {"repository_id": "repo-backend", "repository_path": "backend", "repository_fingerprint": "fp"},
                    {"repository_id": "repo-backend", "repository_path": "backend", "repository_fingerprint": "fp"},
                ),
            ),
            diagnostics,
        )
        with patch("ai_workflow.cli.gather_workspace_detailed", return_value=result):
            packet = self.run_cli("brief", "Fix typo in README")
            prompt = self.run_cli_text("brief", "Fix typo in README", "--format", "prompt")

        orchestration = packet["retrieval"]["workspace_orchestration"]
        self.assertEqual(orchestration["workspace_fingerprint"], "workspace-fp")
        self.assertEqual(orchestration["repositories_searched"], ["repo-backend", "repo-frontend"])
        self.assertEqual(packet["changed_files_detected"], ["backend/payments.py"])
        self.assertLessEqual(orchestration["budget"]["allocated_context_chars"], orchestration["budget"]["parent_context_chars"])
        self.assertIn("[REPOSITORIES] selected=backend, frontend skipped=docs", prompt)
        self.assertIn("[REPO_BUDGET] allocated=1000 used=120", prompt)
        self.assertNotIn(str(self.root.resolve()), prompt)


if __name__ == "__main__":
    unittest.main()
