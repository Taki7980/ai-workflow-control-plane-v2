import unittest

from ai_workflow.benchmark_corpus import corpus_summary, validate_corpus_document


def positive_case(case_id="case-1"):
    return {
        "schema_version": 2,
        "case_id": case_id,
        "task": "Where is login validation handled?",
        "task_type": "comment2context",
        "control_type": "positive",
        "repository_id": "repo-a",
        "repository_path": ".",
        "base_commit": "a" * 40,
        "content_manifest_sha256": "b" * 64,
        "gold_files": ["src/auth.py"],
        "gold_spans": [
            {
                "repository_id": "repo-a",
                "path": "src/auth.py",
                "start_line": 10,
                "end_line": 20,
            }
        ],
        "language": "python",
        "label_source": "human_and_verified_patch",
        "labeler_count": 2,
        "budget_tokens": 8192,
        "budget_lines": 400,
    }


def document(cases):
    return {
        "schema_version": 2,
        "corpus_id": "test-corpus",
        "source": {
            "name": "test-source",
            "url": "https://example.test/source",
            "license": "test-only",
        },
        "split": "test",
        "cases": cases,
    }


class BenchmarkCorpusTests(unittest.TestCase):
    def test_valid_v2_document_reports_research_readiness_blockers(self):
        summary = corpus_summary(document([positive_case()]))

        self.assertEqual(summary["cases"], 1)
        self.assertEqual(summary["span_labeled_cases"], 1)
        self.assertFalse(summary["publication_readiness"]["ready"])
        self.assertIn(
            "insufficient_cases",
            summary["publication_readiness"]["blockers"],
        )
        self.assertIn(
            "missing_natural_no_gold_controls",
            summary["publication_readiness"]["blockers"],
        )

    def test_selective_control_requires_provenance(self):
        case = {
            **positive_case("control-1"),
            "task": "Explain a subsystem absent from this snapshot",
            "task_type": "no_gold",
            "control_type": "natural_no_gold",
            "gold_files": [],
            "gold_spans": [],
        }

        with self.assertRaisesRegex(ValueError, "control_source"):
            validate_corpus_document(document([case]))

    def test_source_metadata_is_required(self):
        value = document([positive_case()])
        value["source"] = {"name": "test-source"}

        with self.assertRaisesRegex(ValueError, "source must define"):
            validate_corpus_document(value)


if __name__ == "__main__":
    unittest.main()
