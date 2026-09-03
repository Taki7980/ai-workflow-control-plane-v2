import tempfile, unittest
from pathlib import Path
from ai_workflow.memory import add_memory, list_memories, prune_stale

class MemoryOpsTests(unittest.TestCase):
    def test_list_and_prune(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / 'a.py'
            f.write_text('content')
            add_memory(root, 'verified-fix', 'test1', 'sum1', files=['a.py'])
            add_memory(root, 'decision', 'test2', 'sum2', files=[])
            
            # List shows both
            mems = list_memories(root)
            self.assertEqual(len(mems), 2)
            self.assertFalse(any(m['stale'] for m in mems))
            
            # Delete file to make first memory stale
            f.unlink()
            
            mems_stale = list_memories(root)
            stale_rec = next(m for m in mems_stale if m['summary'] == 'sum1')
            self.assertTrue(stale_rec['stale'])

            # Prune should drop 'sum1' but keep 'sum2'
            res = prune_stale(root)
            self.assertEqual(res['kept'], 1)
            self.assertEqual(res['pruned'], 1)

            final_mems = list_memories(root)
            self.assertEqual(len(final_mems), 1)
            self.assertEqual(final_mems[0]['summary'], 'sum2')