import unittest

from ai_workflow.benchmark import retrieval_metrics


class V22BenchmarkTests(unittest.TestCase):
    def test_metrics_expose_matched_pattern_count_and_density(self):
        class Item:
            def __init__(self, text): self.text = text
        metrics = retrieval_metrics([Item('alpha evidence'), Item('noise')], ['alpha'], 2)
        self.assertEqual(metrics['matched_patterns'], 1)
        self.assertEqual(metrics['relevant_item_density'], 0.5)


if __name__ == '__main__':
    unittest.main()
