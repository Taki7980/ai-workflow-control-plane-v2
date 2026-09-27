import tempfile
import unittest
from unittest.mock import patch

from ai_workflow.commands.parser import build_parser
from ai_workflow.commands.replay import cmd_replay


class ReplayCommandTests(unittest.TestCase):
    def test_parser_exposes_replay_strict_mode(self):
        args = build_parser().parse_args(
            ["--root", ".", "replay", "run-123", "--strict"]
        )

        self.assertEqual(args.run_id, "run-123")
        self.assertTrue(args.strict)
        self.assertIs(args.func, cmd_replay)

    def test_strict_replay_exits_nonzero_on_drift(self):
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.commands.replay.load_config",
            return_value={"version": 2},
        ), patch(
            "ai_workflow.commands.replay.replay_run_journal",
            return_value={
                "found": True,
                "integrity": {"valid": True},
                "compatibility": {"compatible": False},
            },
        ), patch("ai_workflow.commands.replay._json"):
            args = build_parser().parse_args(
                ["--root", td, "replay", "run-123", "--strict"]
            )
            with self.assertRaises(SystemExit) as raised:
                args.func(args)

        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
