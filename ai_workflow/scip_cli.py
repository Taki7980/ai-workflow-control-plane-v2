from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .code_review_graph import find_workspace_root
from .path_policy import PathOutsideWorkspace, resolve_within_root
from .scip import scip_status, sync_scip_index


_COMMANDS = {"status", "sync"}
_LANGUAGES = ("python", "typescript", "javascript", "java", "go")


def handles(argv: Sequence[str]) -> bool:
    return len(argv) >= 2 and argv[0] == "scip" and argv[1] in _COMMANDS


def _repository(workspace: Path, value: str) -> Path:
    if value in {"", "."}:
        return workspace
    try:
        return resolve_within_root(workspace, value)
    except (PathOutsideWorkspace, OSError) as exc:
        raise ValueError("SCIP repository must stay inside the workspace") from exc


def _print(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_status(args: argparse.Namespace) -> None:
    workspace = find_workspace_root(Path.cwd())
    _print(scip_status(workspace, _repository(workspace, args.repository)))


def cmd_sync(args: argparse.Namespace) -> None:
    workspace = find_workspace_root(Path.cwd())
    _print(
        sync_scip_index(
            workspace,
            _repository(workspace, args.repository),
            language=args.language,
            timeout_seconds=args.timeout_seconds,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-workflow")
    top = parser.add_subparsers(dest="command", required=True)
    scip = top.add_parser("scip")
    commands = scip.add_subparsers(dest="scip_command", required=True)

    status = commands.add_parser("status")
    status.add_argument("--repository", default=".")
    status.set_defaults(func=cmd_status)

    sync = commands.add_parser("sync")
    sync.add_argument("--repository", default=".")
    sync.add_argument("--language", choices=_LANGUAGES)
    sync.add_argument("--timeout-seconds", type=int, default=180)
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)
