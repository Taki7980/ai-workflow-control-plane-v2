import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_workflow.run_cli import build_parser, handles, main


class RunCliTests(unittest.TestCase):
    def test_parser_and_dispatch_contract(self):
        inspect_args = build_parser().parse_args(
            ["run", "inspect", "run-123"]
        )
        verify_args = build_parser().parse_args(
            ["run", "verify", "run-123"]
        )

        self.assertEqual(inspect_args.run_command, "inspect")
        self.assertEqual(verify_args.run_command, "verify")
        self.assertEqual(inspect_args.run_id, "run-123")
        self.assertTrue(handles(["run", "inspect", "run-123"]))
        self.assertTrue(handles(["run", "verify", "run-123"]))
        self.assertFalse(handles(["scip", "status"]))

    @patch("ai_workflow.run_cli.read_run_journal")
    def test_inspect_prints_journal_json(self, read):
        read.return_value = {
            "run_id": "run-123",
            "policy_identity": {"config_digest": "cfg"},
        }
        with redirect_stdout(io.StringIO()) as stdout:
            main(["run", "inspect", "run-123"])
        self.assertIn('"run_id": "run-123"', stdout.getvalue())

    @patch("ai_workflow.run_cli.verify_run_journal")
    @patch("ai_workflow.run_cli.load_config")
    def test_verify_prints_compatibility_without_provider_execution(
        self,
        load_config,
        verify,
    ):
        load_config.return_value = {"version": 2}
        verify.return_value = {
            "run_id": "run-123",
            "compatible": True,
            "mismatches": [],
        }

        with tempfile.TemporaryDirectory() as td:
            with (
                patch("ai_workflow.run_cli.Path.cwd", return_value=Path(td)),
                redirect_stdout(io.StringIO()) as stdout,
            ):
                main(["run", "verify", "run-123"])

        verify.assert_called_once()
        self.assertIn('"compatible": true', stdout.getvalue().lower())

    @patch("ai_workflow.run_cli.read_run_journal", return_value=None)
    def test_inspect_missing_run_exits_nonzero(self, _read):
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                main(["run", "inspect", "missing"])


if __name__ == "__main__":
    unittest.main()
