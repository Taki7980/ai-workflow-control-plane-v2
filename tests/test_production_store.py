import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.config import default_config
from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.production_store import (
    append_production_event,
    production_store_path,
    production_store_status,
    reconcile_learning_store,
    sync_learning_store,
)
from ai_workflow.retrieval_learning import (
    choose_learning_decision,
    record_verified_outcome,
    write_learning_decision,
    write_learning_observation,
)


def production_config():
    config = default_config()
    config["context"]["production"]["enabled"] = True
    config["context"]["production"]["sqlite_path"] = (
        "ai-workspace/generated/learning/production/test.sqlite3"
    )
    config["context"]["learning"]["mode"] = "observe"
    return config


class ProductionStoreTests(unittest.TestCase):
    def test_mirrors_learning_lifecycle_and_reconciles(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decision = choose_learning_decision(
                "find payment retry helper",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
            )
            write_learning_decision(root, decision, config)
            write_learning_observation(
                root,
                decision.decision_id,
                elapsed_ms=12.5,
                used_chars=500,
                fallback_count=0,
                sufficiency_score=0.9,
                evidence_state="sufficient",
                config=config,
            )
            record_verified_outcome(
                root,
                decision.decision_id,
                success=True,
                source="verification-suite",
                reward=1.0,
                realized_cost=0.2,
                config=config,
            )

            status = production_store_status(root, config)
            synced = sync_learning_store(root, config)
            reconciliation = reconcile_learning_store(root, config)

        self.assertEqual(status["journal_mode"], "wal")
        self.assertEqual(status["integrity_check"], "ok")
        self.assertEqual(status["event_count"], 3)
        self.assertEqual(status["events_by_type"]["decision"], 1)
        self.assertEqual(status["events_by_type"]["observation"], 1)
        self.assertEqual(status["events_by_type"]["outcome"], 1)
        self.assertEqual(synced["inserted"], 0)
        self.assertEqual(synced["already_present"], 3)
        self.assertTrue(reconciliation["consistent"])

    def test_reconcile_detects_canonical_file_tampering(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decision = choose_learning_decision(
                "find payment retry helper",
                RouteDecision(Lane.SMALL, Risk.LOW),
                "exact",
                config,
            )
            path = Path(write_learning_decision(root, decision, config))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["safety_reason"] = "tampered"
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            reconciliation = reconcile_learning_store(root, config)

        self.assertFalse(reconciliation["consistent"])
        self.assertEqual(len(reconciliation["digest_mismatches"]), 1)

    def test_same_event_id_with_different_payload_is_rejected(self):
        config = production_config()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = production_store_path(root, config)
            append_production_event(
                store,
                "decision",
                {"decision_id": "a" * 32, "value": 1},
                event_id="decision:" + "a" * 32,
            )
            with self.assertRaises(ValueError):
                append_production_event(
                    store,
                    "decision",
                    {"decision_id": "a" * 32, "value": 2},
                    event_id="decision:" + "a" * 32,
                )


if __name__ == "__main__":
    unittest.main()
