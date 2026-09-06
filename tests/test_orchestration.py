import unittest

from ai_workflow.models import Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus


class OrchestrationTests(unittest.TestCase):
    def test_answer_contract_is_direct_and_minimal(self):
        from ai_workflow.orchestration import build_orchestration_contract
        decision = RouteDecision(Lane.ANSWER, Risk.LOW, ['read only'], False, 0.9)
        result = build_orchestration_contract(decision, {'retrieval_intent': 'exact', 'sufficiency': {'sufficient': True}}, [], 1, ProviderStatus(False, False, False, False), {})
        self.assertEqual(result['superpowers_skills'], [])
        self.assertEqual(result['agent_slots'], 1)

    def test_structural_full_uses_crg_and_superpowers_sequence(self):
        from ai_workflow.orchestration import build_orchestration_contract
        decision = RouteDecision(Lane.FULL, Risk.MEDIUM, ['structural'], True, 0.8)
        result = build_orchestration_contract(decision, {'retrieval_intent': 'structural', 'sufficiency': {'sufficient': False}}, ['a.py', 'b.py'], 2, ProviderStatus(True, True, False, True), {})
        self.assertIn('get_minimal_context_tool', result['crg_plan'])
        self.assertIn('get_impact_radius_tool', result['crg_plan'])
        self.assertIn('writing-plans', result['superpowers_skills'])
        self.assertIn('subagent-driven-development', result['superpowers_skills'])

    def test_high_risk_contract_strengthens_review_without_breaking_budget(self):
        from ai_workflow.orchestration import build_orchestration_contract
        decision = RouteDecision(Lane.FULL, Risk.HIGH, ['payment'], True, 0.9)
        config = {'execution': {'orchestration_budget': {'max_agent_slots': 6, 'max_crg_calls': 8, 'review_passes': 3, 'verification_passes': 3}}}
        result = build_orchestration_contract(decision, {'retrieval_intent': 'structural', 'sufficiency': {'sufficient': False}}, ['a.py', 'b.py', 'c.py'], 1, ProviderStatus(True, True, False, True), config)
        budget = result['budget']
        self.assertLessEqual(result['agent_slots'], budget['max_agent_slots'])
        self.assertLessEqual(len(result['crg_plan']), budget['max_crg_calls'])
        self.assertGreaterEqual(result['review_passes'], 2)
        self.assertGreaterEqual(result['verification_passes'], 2)


if __name__ == '__main__':
    unittest.main()
