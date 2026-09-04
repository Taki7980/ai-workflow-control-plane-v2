import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.providers import detect, execution_provider, model_tier

ROOT = Path(__file__).parents[1]
CFG = json.loads((ROOT/'ai-workspace/config/control-plane.json').read_text())

class ProviderTests(unittest.TestCase):
    def test_superpowers_can_be_forced_for_marketplace_installs(self):
        with patch.dict(os.environ, {'AI_WORKFLOW_SUPERPOWERS':'1'}):
            status = detect(ROOT, CFG)
            self.assertTrue(status.superpowers)
            self.assertEqual(execution_provider(Lane.FULL, CFG, status), 'superpowers')
    def test_crg_is_available_only_when_its_graph_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch('ai_workflow.providers.shutil.which', return_value='code-review-graph'):
                self.assertFalse(detect(root, CFG).code_review_graph)
                graph = root / '.code-review-graph' / 'graph.db'
                graph.parent.mkdir()
                graph.touch()
                self.assertTrue(detect(root, CFG).code_review_graph)

    def test_model_tier_scales_with_risk(self):
        low = RouteDecision(Lane.SMALL, Risk.LOW)
        high = RouteDecision(Lane.FULL, Risk.HIGH)
        self.assertEqual(model_tier(low, CFG), 'fast')
        self.assertEqual(model_tier(high, CFG), 'capable')
