from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .code_review_graph import find_workspace_root
from .config import default_config, load_config
from .run_journal import read_run_journal, verify_run_journal


_COMMANDS = {"inspect", "verify"}


def handles(argv: Sequence[str]) -> bool:
    return (
        len(argv) >= 3
        and argv[0] == "run"
        and argv[1] in _COMMANDS
    )


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _config(root: Path) -> dict:
    try:
        return load_config(root)
    except FileNotFoundError:
        return default_config()


def cmd_inspect(args: argparse.Namespace) -> None:
    root = find_workspace_root(Path.cwd())
    record = read_run_journal(root, args.run_id)
    if record is None:
        _print(
            {
                "run_id": args.run_id,
                "error": "run journal not found",
            }
        )
        raise SystemExit(1)
    _print(record)


def cmd_verify(args: argparse.Namespace) -> None:
    root = find_workspace_root(Path.cwd())
    _print(
        verify_run_journal(
            root,
            args.run_id,
            _config(root),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-workflow")
    top = parser.add_subparsers(dest="command", required=True)
    run = top.add_parser("run")
    commands = run.add_subparsers(dest="run_command", required=True)

    inspect = commands.add_parser("inspect")
    inspect.add_argument("run_id")
    inspect.set_defaults(func=cmd_inspect)

    verify = commands.add_parser("verify")
    verify.add_argument("run_id")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)
