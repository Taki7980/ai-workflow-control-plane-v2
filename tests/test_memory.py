import tempfile, unittest
from pathlib import Path
from ai_workflow.memory import add_memory, search_memory

class MemoryTests(unittest.TestCase):
    def test_hash_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root/'ai-workspace/memory').mkdir(parents=True)
            f=root/'a.py'; f.write_text('x=1')
            add_memory(root,'verified-fix','alpha bug','fixed alpha',files=['a.py'])
            self.assertFalse(search_memory(root,'alpha')[0]['stale'])
            f.write_text('x=2')
            self.assertTrue(search_memory(root,'alpha')[0]['stale'])
            self.assertEqual(len(search_memory(root,'alpha',exclude_stale=True)), 0)
