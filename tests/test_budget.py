import unittest, json
from pathlib import Path
from ai_workflow.budget import budget_for, truncate
from ai_workflow.models import Lane
CFG = json.loads((Path(__file__).parents[1] / 'ai-workspace/config/control-plane.json').read_text())
class BudgetTests(unittest.TestCase):
    def test_lane_budgets_increase(self):
        self.assertLess(budget_for(Lane.ANSWER, CFG).estimated_tokens, budget_for(Lane.SMALL, CFG).estimated_tokens)
        self.assertLess(budget_for(Lane.SMALL, CFG).estimated_tokens, budget_for(Lane.FULL, CFG).estimated_tokens)
    def test_truncate_marks_loss(self):
        text, cut = truncate('x'*1000, 100)
        self.assertTrue(cut); self.assertLessEqual(len(text), 130)
