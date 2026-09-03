import unittest
from ai_workflow.compress import compress_text

class CompressTests(unittest.TestCase):
    def test_basic_compression_fallback(self):
        long_text = "\n".join(f"line {i}" for i in range(100))
        res = compress_text(long_text, max_lines=20, max_chars=1000, prefer_rtk=False)
        self.assertIn("LINES OMITTED", res)
        self.assertLessEqual(len(res.splitlines()), 22)
