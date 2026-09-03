import unittest, json
from pathlib import Path
from ai_workflow.classifier import classify
from ai_workflow.models import Lane, Risk

CFG = json.loads((Path(__file__).parents[1] / 'ai-workspace/config/control-plane.json').read_text())

class ClassifierTests(unittest.TestCase):
    def test_answer(self):
        self.assertEqual(classify('explain how this service works', CFG).lane, Lane.ANSWER)
    def test_sensitive_read_only_stays_answer(self):
        self.assertEqual(classify('explain how auth works', CFG).lane, Lane.ANSWER)
    def test_high_risk_forces_full(self):
        d = classify('small fix to payment auth', CFG)
        self.assertEqual(d.lane, Lane.FULL); self.assertEqual(d.risk, Risk.HIGH)
    def test_small_known_file(self):
        self.assertEqual(classify('rename typo in src/ui.ts', CFG).lane, Lane.SMALL)
    def test_structural_full(self):
        d = classify('what is the blast radius if ProcessPayment changes?', CFG)
        self.assertEqual(d.lane, Lane.FULL); self.assertTrue(d.structural_context)

    def test_author_does_not_trigger_auth_high_risk(self):
        d = classify('who is the author of src/ui.ts', CFG)
        self.assertEqual(d.lane, Lane.ANSWER)
        self.assertEqual(d.risk, Risk.LOW)
