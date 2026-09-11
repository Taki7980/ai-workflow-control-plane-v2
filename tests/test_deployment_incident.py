import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.deployment_incident import (
    create_incident_bundle,
    verify_incident_bundle,
    write_incident_bundle,
)
from ai_workflow.io_utils import atomic_write_json
from ai_workflow.retrieval_learning import learning_root


class DeploymentIncidentTests(unittest.TestCase):
    def test_bundle_is_signed_and_excludes_raw_learning_payload(self):
        key = b"incident-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = learning_root(root)
            decision_id = "a" * 32
            atomic_write_json(
                base / "decisions" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "task_fingerprint": "hash-only",
                    "raw_task_text": "do not export this",
                    "repository_content": "secret source",
                    "deployment": {
                        "policy_id": "policy-123",
                        "assignment": "candidate",
                    },
                },
            )
            atomic_write_json(
                base / "outcomes" / f"{decision_id}.json",
                {
                    "decision_id": decision_id,
                    "verified": True,
                    "success": False,
                    "source": "verification-suite",
                    "reward": 0.0,
                },
            )
            state = {
                "policy_id": "policy-123",
                "generation": 4,
                "stage": "rolled_back",
                "history": [{"to": "rolled_back"}],
            }
            report = {
                "gate": {
                    "rollback_required": True,
                    "rollback_blockers": ["failure_budget"],
                }
            }

            bundle = create_incident_bundle(
                root,
                state,
                report,
                key,
                reason="failure budget exceeded",
            )
            verification = verify_incident_bundle(bundle, key)
            serialized = json.dumps(bundle)
            path = write_incident_bundle(root, bundle, key)

        self.assertTrue(verification["valid"])
        self.assertNotIn("do not export this", serialized)
        self.assertNotIn("secret source", serialized)
        self.assertTrue(bundle["privacy"]["raw_task_text"] is False)
        self.assertTrue(Path(path).name.endswith(".json"))

    def test_tampering_invalidates_incident_signature(self):
        key = b"incident-key"
        with tempfile.TemporaryDirectory() as temp:
            bundle = create_incident_bundle(
                Path(temp),
                {
                    "policy_id": "policy-123",
                    "generation": 2,
                    "stage": "rolled_back",
                    "history": [],
                },
                {"gate": {"rollback_required": True}},
                key,
                reason="original reason",
            )

        bundle["reason"] = "tampered"
        result = verify_incident_bundle(bundle, key)

        self.assertFalse(result["valid"])
        self.assertIn("signature_mismatch", result["errors"])

    def test_incident_writer_is_immutable(self):
        key = b"incident-key"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = create_incident_bundle(
                root,
                {
                    "policy_id": "policy-123",
                    "generation": 2,
                    "stage": "rolled_back",
                    "history": [],
                },
                {"gate": {"rollback_required": True}},
                key,
                reason="manual rollback",
            )
            write_incident_bundle(root, bundle, key)
            with self.assertRaises(FileExistsError):
                write_incident_bundle(root, bundle, key)


if __name__ == "__main__":
    unittest.main()
