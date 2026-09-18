import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ai_workflow.scip_cli import build_parser, handles, main


class ScipCliTests(unittest.TestCase):
    def test_parser_and_dispatch_contract(self):
        status = build_parser().parse_args(["scip", "status"])
        sync = build_parser().parse_args(
            ["scip", "sync", "--language", "python"]
        )

        self.assertEqual(status.scip_command, "status")
        self.assertEqual(sync.scip_command, "sync")
        self.assertEqual(sync.language, "python")
        self.assertTrue(handles(["scip", "status"]))
        self.assertTrue(handles(["scip", "sync"]))
        self.assertFalse(handles(["benchmark-corpus", "validate"]))

    @patch("ai_workflow.scip_cli.scip_status")
    def test_status_prints_json(self, status):
        status.return_value = {"ready": False, "reason": "missing index"}
        with redirect_stdout(io.StringIO()) as stdout:
            main(["scip", "status"])
        self.assertIn('"ready": false', stdout.getvalue().lower())

    @patch("ai_workflow.scip_cli.sync_scip_index")
    def test_sync_prints_result(self, sync):
        sync.return_value = {
            "ready": True,
            "language": "go",
            "indexer": "scip-go",
        }
        with redirect_stdout(io.StringIO()) as stdout:
            main(["scip", "sync", "--language", "go"])
        self.assertIn('"indexer": "scip-go"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
