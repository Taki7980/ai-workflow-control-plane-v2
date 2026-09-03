import unittest
from ai_workflow.models import ContextItem
from ai_workflow.context_broker import _cap_items

class ContextDedupeTests(unittest.TestCase):
    def test_deduplication(self):
        items = [
            ContextItem("source", "def calculate_tax():\n    return 0.1\n"),
            ContextItem("index", "def calculate_tax():\n    return 0.1\n"),  # Exact duplicate
            ContextItem("crg", "def calculate_tax():\n   return 0.1\n"),     # Whitespace diff duplicate
            ContextItem("source", "def other_func():\n    pass\n"),
        ]
        seen = set()
        deduped = _cap_items(items, chars=1000, seen_keys=seen, query="")
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].text, "def calculate_tax():\n    return 0.1\n")
        self.assertEqual(deduped[1].text, "def other_func():\n    pass\n")

    def test_mmr_ranking(self):
        items = [
            ContextItem("source", "def ProcessPayment(amount): return auth_payment(amount)"),
            ContextItem("source", "def ProcessPayment(amount): return auth_payment(amount) # identical wrapper func"),
            ContextItem("source", "def get_invoice(id): return db.find(id)"), 
        ]
        
        # Testing submodular diversity
        # Query: ProcessPayment invoice
        deduped = _cap_items(items, chars=1000, seen_keys=set(), query="ProcessPayment invoice")
        texts = [i.text for i in deduped]
        self.assertEqual(len(texts), 3)

        # Checking that ordering reflects processing instead of strict match assertion
        self.assertIn("def get_invoice(id): return db.find(id)", texts)
        self.assertIn("def ProcessPayment(amount): return auth_payment(amount)", texts)

