import tempfile
import unittest
from pathlib import Path


class WorkspaceStateTests(unittest.TestCase):
    def test_fingerprint_is_stable_until_content_changes(self):
        from ai_workflow.workspace_state import workspace_fingerprint
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'ai-workspace/generated').mkdir(parents=True)
            (root / 'ai-workspace/generated/index-state.json').write_text('{"version":2,"files":{}}')
            source = root / 'app.py'
            source.write_text('value = 1\n')
            first = workspace_fingerprint(root, ['app.py'])
            second = workspace_fingerprint(root, ['app.py'])
            self.assertEqual(first['fingerprint'], second['fingerprint'])
            source.write_text('value = 2\n')
            third = workspace_fingerprint(root, ['app.py'])
            self.assertNotEqual(first['fingerprint'], third['fingerprint'])

    def test_missing_changed_file_is_encoded_not_ignored(self):
        from ai_workflow.workspace_state import workspace_fingerprint
        with tempfile.TemporaryDirectory() as td:
            result = workspace_fingerprint(Path(td), ['missing.py'])
            self.assertEqual(result['changed_files'][0]['state'], 'missing')


if __name__ == '__main__':
    unittest.main()
