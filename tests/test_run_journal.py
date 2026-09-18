import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.code_review_graph import workspace_graph_fingerprint
from ai_workflow.run_journal import (
    read_run_journal,
    verify_run_journal,
    write_run_journal,
)


class GraphIdentityTests(unittest.TestCase):
    def test_graph_fingerprint_is_path_independent_and_stable(self):
        freshness = {
            "fresh": True,
            "graph_sha256": "a" * 64,
            "repository_fingerprint": "repo-fp",
            "git_head": "abc",
        }
        first_rows = [
            {
                "relative_path": "backend",
                "repository_root": Path("/tmp/one/backend"),
                "data_dir": Path("/tmp/one/state"),
            }
        ]
        second_rows = [
            {
                "relative_path": "backend",
                "repository_root": Path("/other/clone/backend"),
                "data_dir": Path("/other/state"),
            }
        ]

        with (
            patch(
                "ai_workflow.code_review_graph.managed_repositories",
                return_value=first_rows,
            ),
            patch(
                "ai_workflow.code_review_graph.graph_freshness",
                return_value=freshness,
            ),
        ):
            first = workspace_graph_fingerprint(Path("/tmp/one"), {})

        with (
            patch(
                "ai_workflow.code_review_graph.managed_repositories",
                return_value=second_rows,
            ),
            patch(
                "ai_workflow.code_review_graph.graph_freshness",
                return_value=freshness,
            ),
        ):
            second = workspace_graph_fingerprint(Path("/other/clone"), {})

        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["repositories"], second["repositories"])


class RunJournalTests(unittest.TestCase):
    def test_journal_is_immutable_and_excludes_raw_text(self):
        record = {
            "run_id": "run-123",
            "policy_identity": {"config_digest": "cfg"},
            "workspace_state": {"fingerprint": "workspace"},
            "graph_state": {"fingerprint": "graph"},
            "retrieval": {
                "retrieval_intent": "exact",
                "providers_attempted": ["base"],
            },
            "selected_evidence": [
                {
                    "source": "lightweight_index",
                    "dedupe_key": "evidence-1",
                    "provenance": {"path": "a.py"},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = write_run_journal(root, record)
            loaded = read_run_journal(root, "run-123")

            self.assertTrue((root / path).is_file())
            self.assertEqual(loaded, record)
            self.assertNotIn("task", str(loaded).lower())
            self.assertNotIn("evidence text", str(loaded).lower())
            with self.assertRaises(FileExistsError):
                write_run_journal(root, record)

    def test_verify_reports_exact_identity_mismatches(self):
        record = {
            "run_id": "run-123",
            "policy_identity": {
                "config_digest": "cfg-a",
                "retrieval_policy_version": "2",
            },
            "workspace_state": {"fingerprint": "workspace-a"},
            "graph_state": {"fingerprint": "graph-a"},
            "retrieval": {},
            "selected_evidence": [],
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run_journal(root, record)

            with (
                patch(
                    "ai_workflow.run_journal.config_digest",
                    return_value="cfg-b",
                ),
                patch(
                    "ai_workflow.run_journal.workspace_fingerprint",
                    return_value={"fingerprint": "workspace-b"},
                ),
                patch(
                    "ai_workflow.run_journal.workspace_graph_fingerprint",
                    return_value={"fingerprint": "graph-a"},
                ),
            ):
                result = verify_run_journal(
                    root,
                    "run-123",
                    {"version": 2},
                )

        self.assertFalse(result["compatible"])
        self.assertEqual(
            set(result["mismatches"]),
            {"config_digest", "workspace_fingerprint"},
        )


if __name__ == "__main__":
    unittest.main()
