import unittest

from ai_workflow.cli import build_parser


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


if __name__ == "__main__":
    unittest.main()
