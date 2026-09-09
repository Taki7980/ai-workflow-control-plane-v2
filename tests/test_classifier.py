import json
import unittest
from pathlib import Path

from ai_workflow.classifier import classify
from ai_workflow.models import Lane, Risk


CFG = json.loads(
    (Path(__file__).parents[1] / "ai-workspace/config/control-plane.json").read_text()
)


class ClassifierTests(unittest.TestCase):
    def test_answer(self):
        self.assertEqual(classify("explain how this service works", CFG).lane, Lane.ANSWER)

    def test_sensitive_read_only_stays_answer(self):
        self.assertEqual(classify("explain how auth works", CFG).lane, Lane.ANSWER)

    def test_high_risk_forces_full(self):
        decision = classify("small fix to payment auth", CFG)
        self.assertEqual(decision.lane, Lane.FULL)
        self.assertEqual(decision.risk, Risk.HIGH)

    def test_high_risk_does_not_imply_structural_context(self):
        for task in (
            "Change authentication token validation",
            "Modify payment schema migration",
            "Deploy a public API contract change",
        ):
            with self.subTest(task=task):
                decision = classify(task, CFG)
                self.assertEqual(decision.lane, Lane.FULL)
                self.assertEqual(decision.risk, Risk.HIGH)
                self.assertFalse(decision.structural_context)

    def test_small_known_file(self):
        self.assertEqual(classify("rename typo in src/ui.ts", CFG).lane, Lane.SMALL)

    def test_structural_full(self):
        decision = classify("what is the blast radius if ProcessPayment changes?", CFG)
        self.assertEqual(decision.lane, Lane.FULL)
        self.assertTrue(decision.structural_context)

    def test_modal_high_risk_mutations_never_use_answer_lane(self):
        cases = [
            "Can you patch auth?",
            "Could you rewrite the payment handler?",
            "Would you alter the production schema?",
        ]
        for task in cases:
            with self.subTest(task=task):
                decision = classify(task, CFG)
                self.assertEqual(decision.lane, Lane.FULL)
                self.assertEqual(decision.risk, Risk.HIGH)

    def test_author_does_not_trigger_auth_high_risk(self):
        decision = classify("who is the author of src/ui.ts", CFG)
        self.assertEqual(decision.lane, Lane.ANSWER)
        self.assertEqual(decision.risk, Risk.LOW)

    def test_unbounded_mutations_require_full(self):
        for task in ('remove unused files and folders', 'fix all bugs',
                     'rename everything', 'update text across project'):
            with self.subTest(task=task):
                self.assertEqual(classify(task, CFG).lane, Lane.FULL)
