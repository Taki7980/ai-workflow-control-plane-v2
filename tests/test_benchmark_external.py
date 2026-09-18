import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.benchmark_external import (
    adapt_agent_retrieval_bench,
    adapt_core_bench,
    external_validation_report,
    load_jsonl,
)


ARB_RECORD = {
    "base_commit": "68b5ff900bae8ee1a0e328c1a2301a7985e4f1c6",
    "gold": {
        "related_tests": ["tests/builder/help.rs"],
        "root_cause_files": ["clap_builder/src/util/mod.rs"],
        "supporting_files": [],
    },
    "id": "3cfa329da72d3c0763b18e77",
    "metadata": {"evidence": {"source": "same_pr_changed_tests"}},
    "query": {
        "changed_file": "clap_builder/src/util/mod.rs",
        "pr_body": "Quote empty default values in help output.",
        "pr_title": "Quote empty default values in help output",
    },
    "repo": "clap-rs/clap",
    "task_type": "code2test",
    "version": 1,
}


def arb_document():
    return adapt_agent_retrieval_bench(
        [ARB_RECORD],
        corpus_id="arb-fixture",
        source_url="https://github.com/eyuansu62/agent-retrieval-bench",
        license_statement="upstream benchmark metadata; repository files retain upstream licenses",
        split="test",
        repository_paths={"clap-rs/clap": "snapshots/clap-rs/clap"},
        languages={"clap-rs/clap": "rust"},
    )


class AgentRetrievalBenchAdapterTests(unittest.TestCase):
    def test_maps_file_level_arb_case_without_fabricating_span_gold(self):
        document = arb_document()
        case = document["cases"][0]

        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(document["source"]["id"], "agent-retrieval-bench")
        self.assertEqual(case["schema_version"], 1)
        self.assertEqual(case["case_id"], ARB_RECORD["id"])
        self.assertEqual(case["task_type"], "code2test")
        self.assertEqual(case["gold_files"], ["tests/builder/help.rs"])
        self.assertNotIn("gold_spans", case)
        self.assertNotIn("content_manifest_sha256", case)
        self.assertEqual(case["repository_id"], "clap-rs/clap")
        self.assertEqual(case["repository_path"], "snapshots/clap-rs/clap")
        self.assertEqual(case["language"], "rust")
        self.assertIn("Quote empty default values", case["task"])
        self.assertIn("clap_builder/src/util/mod.rs", case["task"])
        self.assertEqual(
            case["external_provenance"]["upstream_case_id"],
            ARB_RECORD["id"],
        )

    def test_rejects_arb_record_without_required_snapshot_identity(self):
        broken = {**ARB_RECORD}
        broken.pop("base_commit")

        with self.assertRaisesRegex(ValueError, "base_commit"):
            adapt_agent_retrieval_bench(
                [broken],
                corpus_id="arb-broken",
                source_url="https://example.test/arb",
                license_statement="test",
                split="test",
            )


class CoreBenchAdapterTests(unittest.TestCase):
    def test_joins_queries_qrels_and_corpus_into_file_gold(self):
        document = adapt_core_bench(
            queries=[{"_id": "q1", "text": "Fix authentication validation"}],
            qrels=[
                {"query-id": "q1", "corpus-id": "doc-a", "score": 1},
                {"query-id": "q1", "corpus-id": "doc-b", "score": 0},
            ],
            corpus=[
                {"_id": "doc-a", "text": "auth chunk", "metadata": {"file": "src/auth.py"}},
                {"_id": "doc-b", "text": "other chunk", "metadata": {"file": "src/other.py"}},
            ],
            repository_id="example/project",
            base_commit="a" * 40,
            corpus_id="core-fixture",
            source_url="https://github.com/zhangfw123/CORE-Bench-Eval",
            license_statement="use upstream dataset terms",
            split="test",
            repository_path="snapshots/example/project",
            language="python",
            task_type="edit2ripple",
        )

        case = document["cases"][0]
        self.assertEqual(document["source"]["id"], "core-bench")
        self.assertEqual(case["schema_version"], 1)
        self.assertEqual(case["task"], "Fix authentication validation")
        self.assertEqual(case["gold_files"], ["src/auth.py"])
        self.assertEqual(case["repository_id"], "example/project")
        self.assertEqual(case["language"], "python")

    def test_rejects_positive_qrel_that_cannot_resolve_to_a_file(self):
        with self.assertRaisesRegex(ValueError, "qrel.*missing corpus"):
            adapt_core_bench(
                queries=[{"_id": "q1", "text": "Fix auth"}],
                qrels=[{"query-id": "q1", "corpus-id": "missing", "score": 1}],
                corpus=[],
                repository_id="example/project",
                base_commit="a" * 40,
                corpus_id="core-broken",
                source_url="https://example.test/core",
                license_statement="test",
                split="test",
            )


class ExternalValidationReportTests(unittest.TestCase):
    def test_reports_source_and_language_coverage(self):
        arb = arb_document()
        core = adapt_core_bench(
            queries=[{"_id": "q1", "text": "Fix handler"}],
            qrels=[{"query-id": "q1", "corpus-id": "doc-a", "score": 1}],
            corpus=[{"_id": "doc-a", "metadata": {"file": "handler.go"}}],
            repository_id="example/go-project",
            base_commit="b" * 40,
            corpus_id="core-fixture",
            source_url="https://github.com/zhangfw123/CORE-Bench-Eval",
            license_statement="test",
            split="test",
            language="go",
        )

        report = external_validation_report(
            [arb, core],
            minimum_languages=2,
        )

        self.assertTrue(report["ready"])
        self.assertEqual(report["sources"], ["agent-retrieval-bench", "core-bench"])
        self.assertEqual(report["cases"], 2)
        self.assertEqual(report["repositories"], 2)
        self.assertEqual(report["languages"], {"go": 1, "rust": 1})
        self.assertEqual(report["blockers"], [])

    def test_duplicate_corpus_ids_fail_closed(self):
        first = arb_document()
        second = {**first, "source": {**first["source"], "id": "core-bench"}}

        with self.assertRaisesRegex(ValueError, "duplicate corpus_id"):
            external_validation_report([first, second])


class JsonlLoaderTests(unittest.TestCase):
    def test_load_jsonl_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text('{"id": 1}\n\n{"id": 2}\n', encoding="utf-8")

            self.assertEqual(load_jsonl(path), [{"id": 1}, {"id": 2}])

    def test_load_jsonl_rejects_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text("{bad json}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSONL"):
                load_jsonl(path)

            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be an object"):
                load_jsonl(path)


class ExternalAdapterEdgeCaseTests(unittest.TestCase):
    def test_arb_fallback_task_and_comment_context_gold(self):
        record = {
            **ARB_RECORD,
            "query": {"issue": 42, "flag": True},
            "task_type": "comment2context",
            "gold": {
                "supporting_files": ["src/support.py", "src/support.py"],
                "root_cause_files": ["src/root.py"],
            },
            "metadata": {},
        }

        document = adapt_agent_retrieval_bench(
            [record],
            corpus_id="arb-fallback",
            source_url="https://example.test/arb",
            license_statement="test",
            split="test",
        )
        case = document["cases"][0]

        self.assertIn("flag: True", case["task"])
        self.assertIn("issue: 42", case["task"])
        self.assertEqual(case["gold_files"], ["src/support.py", "src/root.py"])
        self.assertEqual(case["label_source"], "agent-retrieval-bench")
        self.assertEqual(case["language"], "unknown")

    def test_arb_rejects_unsupported_or_empty_gold(self):
        unsupported = {**ARB_RECORD, "task_type": "unknown"}
        with self.assertRaisesRegex(ValueError, "unsupported Agent Retrieval Bench"):
            adapt_agent_retrieval_bench(
                [unsupported],
                corpus_id="arb-unsupported",
                source_url="https://example.test/arb",
                license_statement="test",
                split="test",
            )

        empty_gold = {
            **ARB_RECORD,
            "gold": {"related_tests": []},
        }
        with self.assertRaisesRegex(ValueError, "no file-level gold"):
            adapt_agent_retrieval_bench(
                [empty_gold],
                corpus_id="arb-empty",
                source_url="https://example.test/arb",
                license_statement="test",
                split="test",
            )

    def test_core_aliases_default_score_and_top_level_path(self):
        document = adapt_core_bench(
            queries=[{"query_id": "q1", "query": "Find auth flow"}],
            qrels=[{"query_id": "q1", "doc_id": "doc-a"}],
            corpus=[{"corpus_id": "doc-a", "path": "src/auth.py"}],
            repository_id="example/project",
            base_commit="c" * 40,
            corpus_id="core-aliases",
            source_url="https://example.test/core",
            license_statement="test",
            split="test",
            language="Python",
        )

        case = document["cases"][0]
        self.assertEqual(case["task"], "Find auth flow")
        self.assertEqual(case["gold_files"], ["src/auth.py"])
        self.assertEqual(case["language"], "Python")

    def test_core_rejects_bad_scores_and_missing_positive_qrels(self):
        with self.assertRaisesRegex(ValueError, "not numeric"):
            adapt_core_bench(
                queries=[{"_id": "q1", "text": "Fix auth"}],
                qrels=[{"query-id": "q1", "corpus-id": "doc-a", "score": "bad"}],
                corpus=[{"_id": "doc-a", "path": "src/auth.py"}],
                repository_id="example/project",
                base_commit="d" * 40,
                corpus_id="core-bad-score",
                source_url="https://example.test/core",
                license_statement="test",
                split="test",
            )

        with self.assertRaisesRegex(ValueError, "no positive qrels"):
            adapt_core_bench(
                queries=[{"_id": "q1", "text": "Fix auth"}],
                qrels=[{"query-id": "q1", "corpus-id": "doc-a", "score": 0}],
                corpus=[{"_id": "doc-a", "path": "src/auth.py"}],
                repository_id="example/project",
                base_commit="e" * 40,
                corpus_id="core-no-positive",
                source_url="https://example.test/core",
                license_statement="test",
                split="test",
            )

    def test_external_report_not_ready_and_minimum_validation(self):
        report = external_validation_report([], minimum_languages=1)
        self.assertFalse(report["ready"])
        self.assertIn("missing_source:agent-retrieval-bench", report["blockers"])
        self.assertIn("missing_source:core-bench", report["blockers"])
        self.assertIn("language_diversity:0<1", report["blockers"])
        self.assertIn("no_cases", report["blockers"])

        with self.assertRaisesRegex(ValueError, "minimum_languages"):
            external_validation_report([], minimum_languages=0)


if __name__ == "__main__":
    unittest.main()
