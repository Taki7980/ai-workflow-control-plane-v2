import tempfile, unittest, json
from pathlib import Path
from ai_workflow.indexer import build_indexes, incremental_indexes, load_state

class IncrementalIndexTests(unittest.TestCase):
    def test_incremental_skips_unchanged_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'ai-workspace/generated').mkdir(parents=True)
            f1 = root / 'a.py'
            f2 = root / 'b.py'
            f1.write_text('def func_a(): pass\n')
            f2.write_text('def func_b(): pass\n')

            # Initial full index
            full_res = build_indexes(root)
            self.assertEqual(full_res['files'], 2)
            self.assertEqual(full_res['symbols'], 2)

            # Incremental with zero changes
            inc1 = incremental_indexes(root)
            self.assertEqual(inc1['skipped'], 2)
            self.assertEqual(inc1['changed'], 0)
            self.assertEqual(inc1['removed'], 0)

            # Modify one file, add one new file
            f1.write_text('def func_a_v2(): pass\n')
            f3 = root / 'c.py'
            f3.write_text('def func_c(): pass\n')

            inc2 = incremental_indexes(root)
            self.assertEqual(inc2['skipped'], 1)  # b.py
            self.assertEqual(inc2['changed'], 2)  # a.py, c.py
            self.assertEqual(inc2['files'], 3)
            self.assertEqual(inc2['symbols'], 3)
            
            # Remove a file
            f2.unlink()
            inc3 = incremental_indexes(root)
            self.assertEqual(inc3['removed'], 1)
            self.assertEqual(inc3['files'], 2)
