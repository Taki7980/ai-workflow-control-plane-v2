import unittest
from pathlib import Path
from ai_workflow.context_broker import resolve_test_files

class TestResolverTests(unittest.TestCase):
    def test_resolve_test_files(self):
        changed = ["ai_workflow/memory.py", "src/auth/login.ts", "components/Button.tsx", "main.go"]
        tests = resolve_test_files(changed)
        self.assertEqual(len(tests), 4)
        self.assertIn("test_memory.py", tests[0]["candidates"])
        self.assertIn("login.test.ts", tests[1]["candidates"])
        self.assertIn("Button.test.tsx", tests[2]["candidates"])
        self.assertIn("main_test.go", tests[3]["candidates"])

