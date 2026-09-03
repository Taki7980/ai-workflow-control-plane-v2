import tempfile, unittest
from pathlib import Path
from ai_workflow.handoff import validate

GOOD='''# Handoff\n- **Lane / risk**: small / low\n- **Goal / state**: x\n- **Exact paths+symbols**: a.py:list[str]\n- **Context sources**: index\n- **Ordered edits**: [x] step 1\n- **Invariants**: x\n- **Changed files**: a.py\n- **Checks**: test\n- **Blockers**: none\n- **Exact next step**: test\n'''
PLACEHOLDER='''# Handoff\n- **Lane / risk**: [answer|small|full] / [low|medium|high]\n- **Goal / state**: [goal and current state]\n- **Exact paths+symbols**: a.py\n- **Context sources**: index\n- **Ordered edits**: x\n- **Invariants**: x\n- **Changed files**: a.py\n- **Checks**: test\n- **Blockers**: none\n- **Exact next step**: test\n'''
class HandoffTests(unittest.TestCase):
    def test_valid_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.ai').mkdir(); (root/'.ai/HANDOFF.md').write_text(GOOD)
            self.assertEqual(validate(root), [])

    def test_placeholder_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'.ai').mkdir(); (root/'.ai/HANDOFF.md').write_text(PLACEHOLDER)
            errors = validate(root)
            self.assertTrue(any("placeholder" in e for e in errors))
