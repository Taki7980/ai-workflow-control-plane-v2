import unittest
from ai_workflow.compress import compress_text
class CompressTests(unittest.TestCase):
    def test_line_cap(self):
        out=compress_text('\n'.join(str(i) for i in range(200)), max_lines=20)
        self.assertIn('LINES OMITTED', out)
