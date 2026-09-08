import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

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
        (self.root / "AGENTS.md").write_text("# {{PROJECT_NAME}}\n", encoding="utf-8")

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
        self.assertTrue((self.root / "AGENTS.md").is_file())
        self.assertTrue((self.root / DEFAULT_RELATIVE).is_file())
        self.assertTrue((self.root / ".ai/PROJECT").is_file())
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
                    (self.root / (DEFAULT_RELATIVE if missing == "config" else "AGENTS.md")).unlink()
                before = self.snapshot()
                with self.assertRaisesRegex(SystemExit, "[Cc]opy.*template"):
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
        self.assertEqual((self.root / "AGENTS.md").read_text(), "# Example\n")
        self.assertEqual((self.root / ".ai/PROJECT").read_text().strip(), str(self.root.resolve()))
        self.assertTrue((self.root / "ai-workspace/generated/index-state.json").is_file())

    def test_answer_brief_does_not_create_state(self):
        self.template()
        before = self.snapshot()
        packet = self.run_cli("brief", "Explain this function", "--write-handoff")
        self.assertEqual(packet["lane"], "answer")
        self.assertEqual(before, self.snapshot())

    def test_answer_brief_preserves_existing_state(self):
        self.template()
        for path in ("ai-workspace/generated/last-brief.json", ".ai/HANDOFF.md"):
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
        self.assertTrue((self.root / ".ai/HANDOFF.md").is_file())
        self.assertEqual(json.loads((self.root / "ai-workspace/generated/last-brief.json").read_text()), packet)


if __name__ == "__main__":
    unittest.main()
