from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .benchmark_corpus import load_corpus_document
from .benchmark_external import (
    adapt_agent_retrieval_bench,
    adapt_core_bench,
    external_validation_report,
    load_jsonl,
)
from .io_utils import atomic_write_json


_EXTERNAL_COMMANDS = {"import-arb", "import-core", "external-report"}


def _json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def handles(argv: Sequence[str]) -> bool:
    return (
        len(argv) >= 2
        and argv[0] == "benchmark-corpus"
        and argv[1] in _EXTERNAL_COMMANDS
    )


def cmd_import_arb(args: argparse.Namespace) -> None:
    document = adapt_agent_retrieval_bench(
        load_jsonl(Path(args.input)),
        corpus_id=args.corpus_id,
        source_url=args.source_url,
        license_statement=args.license_statement,
        split=args.split,
    )
    atomic_write_json(Path(args.output), document)
    _json(document)


def cmd_import_core(args: argparse.Namespace) -> None:
    document = adapt_core_bench(
        load_jsonl(Path(args.queries)),
        load_jsonl(Path(args.qrels)),
        load_jsonl(Path(args.corpus)),
        repository_id=args.repository_id,
        base_commit=args.base_commit,
        corpus_id=args.corpus_id,
        source_url=args.source_url,
        license_statement=args.license_statement,
        split=args.split,
        repository_path=args.repository_path,
        language=args.language,
        task_type=args.task_type,
    )
    atomic_write_json(Path(args.output), document)
    _json(document)


def cmd_external_report(args: argparse.Namespace) -> None:
    documents = [load_corpus_document(Path(path)) for path in args.input]
    report = external_validation_report(
        documents,
        minimum_languages=args.minimum_languages,
    )
    if args.output:
        atomic_write_json(Path(args.output), report)
    _json(report)
    if args.require_ready and not report["ready"]:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    corpus = subparsers.add_parser("benchmark-corpus")
    commands = corpus.add_subparsers(dest="benchmark_corpus_command", required=True)

    arb = commands.add_parser("import-arb")
    arb.add_argument("--input", required=True)
    arb.add_argument("--output", required=True)
    arb.add_argument("--corpus-id", required=True)
    arb.add_argument("--source-url", required=True)
    arb.add_argument("--license-statement", required=True)
    arb.add_argument("--split", required=True)
    arb.set_defaults(func=cmd_import_arb)

    core = commands.add_parser("import-core")
    core.add_argument("--queries", required=True)
    core.add_argument("--qrels", required=True)
    core.add_argument("--corpus", required=True)
    core.add_argument("--output", required=True)
    core.add_argument("--repository-id", required=True)
    core.add_argument("--base-commit", required=True)
    core.add_argument("--corpus-id", required=True)
    core.add_argument("--source-url", required=True)
    core.add_argument("--license-statement", required=True)
    core.add_argument("--split", required=True)
    core.add_argument("--repository-path", default=".")
    core.add_argument("--language", default="unknown")
    core.add_argument("--task-type", default="edit2ripple")
    core.set_defaults(func=cmd_import_core)

    report = commands.add_parser("external-report")
    report.add_argument("--input", action="append", required=True)
    report.add_argument("--output")
    report.add_argument("--minimum-languages", type=int, default=4)
    report.add_argument("--require-ready", action="store_true")
    report.set_defaults(func=cmd_external_report)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)
