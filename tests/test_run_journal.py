import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.code_review_graph import workspace_graph_fingerprint
from ai_workflow.run_journal import (
    EXPECTED_REPLAY_EVENT_KINDS,
    REPLAY_MODE,
    REPLAY_SCHEMA_VERSION,
    build_replay_journal,
    read_run_journal,
    replay_run_journal,
    verify_replay_journal,
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
    def _replay_record(self) -> dict:
        retrieval = {
            "retrieval_intent": "exact",
            "providers_attempted": ["base"],
        }
        selected = [
            {
                "source": "lightweight_index",
                "dedupe_key": "evidence-1",
                "stale": False,
                "score": 1.0,
                "evidence": {
                    "evidence_id": "evidence-v1:abc",
                    "repository_id": "repo-1",
                    "content_sha256": "sha256:" + "a" * 64,
                },
                "metadata": {"path": "a.py"},
                "provenance": {"path": "a.py"},
            }
        ]
        events = [
            {
                "kind": "routing",
                "payload": {"lane": "small", "risk": "low"},
            },
            {
                "kind": "repository_routing",
                "payload": {
                    "strategy": "repository_first_graph_expansion",
                    "repositories": [],
                },
            },
            {
                "kind": "retrieval",
                "payload": retrieval,
            },
            {
                "kind": "ranking",
                "payload": {
                    "candidate_count": 1,
                    "candidates": [
                        {
                            "rank": 1,
                            "source": "lightweight_index",
                            "dedupe_key": "evidence-1",
                        }
                    ],
                },
            },
            {
                "kind": "selection",
                "payload": {
                    "selected_count": 1,
                    "selected_evidence": selected,
                },
            },
            {
                "kind": "orchestration",
                "payload": {"agent_slots": 1},
            },
            {
                "kind": "authorization",
                "payload": {"schema": "capability-v2"},
            },
        ]
        return build_replay_journal(
            {
                "run_id": "run-123",
                "policy_identity": {
                    "config_digest": "cfg-a",
                    "retrieval_policy_version": "2",
                },
                "workspace_state": {"fingerprint": "workspace-a"},
                "graph_state": {"fingerprint": "graph-a"},
                "repository_state": {
                    "fingerprint": "repository-a",
                    "repository_count": 1,
                },
                "changed_files": [],
                "provider_versions": {},
                "retrieval": retrieval,
                "selected_evidence": selected,
            },
            events,
        )

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

    def test_build_requires_exact_v2_event_contract(self):
        record = self._replay_record()
        raw_events = [
            {
                "kind": event["kind"],
                "payload": event["payload"],
            }
            for event in record["replay_events"]
            if event["kind"] != "ranking"
        ]
        source = {
            key: value
            for key, value in record.items()
            if key
            not in {
                "schema_version",
                "replay_mode",
                "replay_event_count",
                "replay_head_digest",
                "replay_events",
                "journal_digest",
            }
        }

        with self.assertRaises(ValueError):
            build_replay_journal(source, raw_events)

    def test_hash_chained_replay_events_detect_tampering(self):
        record = self._replay_record()

        valid = verify_replay_journal(record)
        self.assertTrue(valid["valid"])
        self.assertEqual(
            valid["event_count"],
            len(EXPECTED_REPLAY_EVENT_KINDS),
        )

        record["replay_events"][0]["payload"]["lane"] = "full"
        invalid = verify_replay_journal(record)

        self.assertFalse(invalid["valid"])
        self.assertIn("event_0_digest_mismatch", invalid["errors"])
        self.assertIn("journal_digest_mismatch", invalid["errors"])

    def test_top_level_identity_tampering_breaks_journal_integrity(self):
        record = self._replay_record()
        record["workspace_state"]["fingerprint"] = "forged-workspace"

        result = verify_replay_journal(record)

        self.assertFalse(result["valid"])
        self.assertIn("journal_digest_mismatch", result["errors"])

    def test_run_id_mismatch_is_rejected(self):
        result = verify_replay_journal(
            self._replay_record(),
            expected_run_id="run-456",
        )

        self.assertFalse(result["valid"])
        self.assertIn("run_id_mismatch", result["errors"])

    def test_malformed_retrieval_fails_closed_without_throwing(self):
        record = self._replay_record()
        record["retrieval"] = []

        result = verify_replay_journal(record)

        self.assertFalse(result["valid"])
        self.assertIn("retrieval_invalid", result["errors"])
        self.assertIn("journal_digest_mismatch", result["errors"])

    def test_invalid_journal_does_not_run_compatibility_or_release_events(self):
        record = self._replay_record()
        record["workspace_state"]["fingerprint"] = "tampered"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run_journal(root, record)
            with (
                patch(
                    "ai_workflow.run_journal.workspace_fingerprint",
                    side_effect=AssertionError("must not run"),
                ),
                patch(
                    "ai_workflow.run_journal.workspace_graph_fingerprint",
                    side_effect=AssertionError("must not run"),
                ),
                patch(
                    "ai_workflow.run_journal.aggregate_workspace_fingerprint",
                    side_effect=AssertionError("must not run"),
                ),
            ):
                replay = replay_run_journal(
                    root,
                    "run-123",
                    {"version": 2},
                )

        self.assertFalse(replay["integrity"]["valid"])
        self.assertEqual(
            replay["compatibility"]["mismatches"],
            ["invalid_journal"],
        )
        self.assertFalse(replay["events_released"])
        self.assertEqual(replay["events"], [])

    def test_replay_is_read_only_and_reports_current_state_drift(self):
        record = self._replay_record()

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
                    return_value={"fingerprint": "workspace-a"},
                ),
                patch(
                    "ai_workflow.run_journal.workspace_graph_fingerprint",
                    return_value={"fingerprint": "graph-a"},
                ),
                patch(
                    "ai_workflow.run_journal.aggregate_workspace_fingerprint",
                    return_value={"fingerprint": "repository-a"},
                ),
            ):
                replay = replay_run_journal(
                    root,
                    "run-123",
                    {"version": 2},
                )

        self.assertTrue(replay["found"])
        self.assertEqual(
            replay["schema_version"],
            REPLAY_SCHEMA_VERSION,
        )
        self.assertEqual(replay["replay_mode"], REPLAY_MODE)
        self.assertTrue(replay["integrity"]["valid"])
        self.assertFalse(replay["compatibility"]["compatible"])
        self.assertEqual(
            replay["compatibility"]["mismatches"],
            ["config_digest"],
        )
        self.assertTrue(replay["read_only"])
        self.assertFalse(replay["external_execution_performed"])
        self.assertTrue(replay["events_released"])
        self.assertEqual(replay["events"][0]["kind"], "routing")

    def test_repository_fingerprint_drift_is_reported(self):
        record = self._replay_record()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_run_journal(root, record)
            with (
                patch(
                    "ai_workflow.run_journal.config_digest",
                    return_value="cfg-a",
                ),
                patch(
                    "ai_workflow.run_journal.workspace_fingerprint",
                    return_value={"fingerprint": "workspace-a"},
                ),
                patch(
                    "ai_workflow.run_journal.workspace_graph_fingerprint",
                    return_value={"fingerprint": "graph-a"},
                ),
                patch(
                    "ai_workflow.run_journal.aggregate_workspace_fingerprint",
                    return_value={"fingerprint": "repository-b"},
                ),
            ):
                replay = replay_run_journal(
                    root,
                    "run-123",
                    {"version": 2},
                )

        self.assertTrue(replay["integrity"]["valid"])
        self.assertFalse(replay["compatibility"]["compatible"])
        self.assertEqual(
            replay["compatibility"]["mismatches"],
            ["repository_fingerprint"],
        )

    def test_verify_reports_exact_identity_mismatches_for_legacy_record(self):
        record = {
            "run_id": "run-123",
            "policy_identity": {
                "config_digest": "cfg-a",
                "retrieval_policy_version": "2",
            },
            "workspace_state": {"fingerprint": "workspace-a"},
            "graph_state": {"fingerprint": "graph-a"},
            "changed_files": [],
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
