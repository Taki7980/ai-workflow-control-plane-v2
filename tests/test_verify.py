import tempfile, unittest, sys
from pathlib import Path
from ai_workflow.verify import verify

GOOD='''# Handoff\n- **Lane / risk**: small / low\n- **Goal / state**: x\n- **Exact paths+symbols**: a.py\n- **Context sources**: source\n- **Ordered edits**: x\n- **Invariants**: x\n- **Changed files**: a.py\n- **Checks**: python\n- **Blockers**: none\n- **Exact next step**: done\n'''
class VerifyTests(unittest.TestCase):
    def test_explicit_check_runs_without_shell(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.ai').mkdir(); (root/'.ai/HANDOFF.md').write_text(GOOD)
            result=verify(root,[f'{sys.executable} -c "print(123)"'],30)
            self.assertTrue(result['ok'])
            self.assertIn('123', result['checks'][0]['output'])
