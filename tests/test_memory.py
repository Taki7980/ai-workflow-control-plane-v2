import tempfile
import unittest
from pathlib import Path

from ai_workflow.memory import add_memory, search_memory


class MemoryTests(unittest.TestCase):
    def test_hash_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ai-workspace/memory").mkdir(parents=True)
            source = root / "a.py"
            source.write_text("x=1")
            add_memory(
                root,
                "verified-fix",
                "alpha bug",
                "fixed alpha",
                files=["a.py"],
            )
            self.assertFalse(search_memory(root, "alpha")[0]["stale"])
            source.write_text("x=2")
            self.assertTrue(search_memory(root, "alpha")[0]["stale"])
            self.assertEqual(
                len(search_memory(root, "alpha", exclude_stale=True)),
                0,
            )

    def test_missing_source_path_is_stale_before_and_after_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            add_memory(
                root,
                "verified-fix",
                "missing source",
                "source-backed fix",
                files=["missing.py"],
            )

            self.assertTrue(search_memory(root, "source")[0]["stale"])
            (root / "missing.py").write_text("created later")
            self.assertTrue(search_memory(root, "source")[0]["stale"])

    def test_auth_query_does_not_match_author_substring(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            add_memory(root, "pattern", "author", "authoring guideline")
            self.assertEqual(search_memory(root, "auth"), [])

    def test_code_identifier_subterms_are_searchable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            add_memory(
                root,
                "verified-fix",
                "ProcessPayment",
                "fixed payment processing",
            )
            self.assertEqual(
                search_memory(root, "payment")[0]["type"],
                "verified-fix",
            )
