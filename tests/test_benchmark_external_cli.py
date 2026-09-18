import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ai_workflow.benchmark_external_cli import build_parser, handles, main


class ExternalBenchmarkCliTests(unittest.TestCase):
    def test_import_arb_parser_contract(self):
        args = build_parser().parse_args(
            [
                "benchmark-corpus",
                "import-arb",
                "--input",
                "arb.jsonl",
                "--output",
                "normalized.json",
                "--corpus-id",
                "arb-release",
                "--source-url",
                "https://github.com/eyuansu62/agent-retrieval-bench",
                "--license-statement",
                "upstream terms",
                "--split",
                "test",
            ]
        )

        self.assertEqual(args.benchmark_corpus_command, "import-arb")
        self.assertEqual(args.input, "arb.jsonl")
        self.assertEqual(args.output, "normalized.json")
        self.assertTrue(handles(["benchmark-corpus", "import-arb"]))

    def test_import_core_parser_contract(self):
        args = build_parser().parse_args(
            [
                "benchmark-corpus",
                "import-core",
                "--queries",
                "queries.jsonl",
                "--qrels",
                "qrels.jsonl",
                "--corpus",
                "corpus.jsonl",
                "--output",
                "normalized.json",
                "--repository-id",
                "example/project",
                "--base-commit",
                "a" * 40,
                "--corpus-id",
                "core-release",
                "--source-url",
                "https://github.com/zhangfw123/CORE-Bench-Eval",
                "--license-statement",
                "upstream terms",
                "--split",
                "test",
            ]
        )

        self.assertEqual(args.benchmark_corpus_command, "import-core")
        self.assertEqual(args.repository_id, "example/project")
        self.assertEqual(args.base_commit, "a" * 40)
        self.assertTrue(handles(["benchmark-corpus", "import-core"]))

    def test_external_report_parser_contract(self):
        args = build_parser().parse_args(
            [
                "benchmark-corpus",
                "external-report",
                "--input",
                "arb.json",
                "--input",
                "core.json",
                "--minimum-languages",
                "2",
            ]
        )

        self.assertEqual(args.benchmark_corpus_command, "external-report")
        self.assertEqual(args.input, ["arb.json", "core.json"])
        self.assertEqual(args.minimum_languages, 2)
        self.assertTrue(handles(["benchmark-corpus", "external-report"]))
        self.assertFalse(handles(["benchmark-corpus", "validate"]))


    def test_command_execution_writes_imports_and_report(self):
        arb_record = {
            "base_commit": "a" * 40,
            "gold": {"related_tests": ["tests/test_auth.py"]},
            "id": "arb-1",
            "query": {"pr_title": "Find auth tests"},
            "repo": "example/project",
            "task_type": "code2test",
            "version": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arb_input = root / "arb.jsonl"
            arb_output = root / "arb.json"
            arb_input.write_text(json.dumps(arb_record) + "\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "benchmark-corpus",
                        "import-arb",
                        "--input",
                        str(arb_input),
                        "--output",
                        str(arb_output),
                        "--corpus-id",
                        "arb-cli",
                        "--source-url",
                        "https://example.test/arb",
                        "--license-statement",
                        "test",
                        "--split",
                        "test",
                    ]
                )

            self.assertTrue(arb_output.exists())
            self.assertEqual(
                json.loads(arb_output.read_text(encoding="utf-8"))["source"]["id"],
                "agent-retrieval-bench",
            )

            queries = root / "queries.jsonl"
            qrels = root / "qrels.jsonl"
            corpus = root / "corpus.jsonl"
            core_output = root / "core.json"
            queries.write_text(
                json.dumps({"_id": "q1", "text": "Find handler"}) + "\n",
                encoding="utf-8",
            )
            qrels.write_text(
                json.dumps({"query-id": "q1", "corpus-id": "doc-a", "score": 1}) + "\n",
                encoding="utf-8",
            )
            corpus.write_text(
                json.dumps({"_id": "doc-a", "path": "handler.go"}) + "\n",
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "benchmark-corpus",
                        "import-core",
                        "--queries",
                        str(queries),
                        "--qrels",
                        str(qrels),
                        "--corpus",
                        str(corpus),
                        "--output",
                        str(core_output),
                        "--repository-id",
                        "example/go-project",
                        "--base-commit",
                        "b" * 40,
                        "--corpus-id",
                        "core-cli",
                        "--source-url",
                        "https://example.test/core",
                        "--license-statement",
                        "test",
                        "--split",
                        "test",
                        "--language",
                        "go",
                    ]
                )

            report_output = root / "report.json"
            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "benchmark-corpus",
                        "external-report",
                        "--input",
                        str(arb_output),
                        "--input",
                        str(core_output),
                        "--minimum-languages",
                        "1",
                        "--output",
                        str(report_output),
                    ]
                )

            report = json.loads(report_output.read_text(encoding="utf-8"))
            self.assertTrue(report["ready"])
            self.assertEqual(
                report["sources"],
                ["agent-retrieval-bench", "core-bench"],
            )

    def test_external_report_require_ready_exits_nonzero(self):
        arb_record = {
            "base_commit": "a" * 40,
            "gold": {"related_tests": ["tests/test_auth.py"]},
            "id": "arb-1",
            "query": {"pr_title": "Find auth tests"},
            "repo": "example/project",
            "task_type": "code2test",
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "arb.jsonl"
            document = root / "arb.json"
            source.write_text(json.dumps(arb_record) + "\n", encoding="utf-8")

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "benchmark-corpus",
                        "import-arb",
                        "--input",
                        str(source),
                        "--output",
                        str(document),
                        "--corpus-id",
                        "arb-only",
                        "--source-url",
                        "https://example.test/arb",
                        "--license-statement",
                        "test",
                        "--split",
                        "test",
                    ]
                )

            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    main(
                        [
                            "benchmark-corpus",
                            "external-report",
                            "--input",
                            str(document),
                            "--minimum-languages",
                            "2",
                            "--require-ready",
                        ]
                    )

    def test_handles_short_and_unrelated_argv(self):
        self.assertFalse(handles([]))
        self.assertFalse(handles(["benchmark-corpus"]))
        self.assertFalse(handles(["other", "import-arb"]))


if __name__ == "__main__":
    unittest.main()
