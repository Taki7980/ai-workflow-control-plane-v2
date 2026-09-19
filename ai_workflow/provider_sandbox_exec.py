from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def _apply_limits(
    *,
    cpu_seconds: int | None,
    memory_mb: int | None,
    file_size_mb: int | None,
    open_files: int | None,
) -> None:
    try:
        import resource
    except ImportError as exc:
        raise RuntimeError(
            "resource limits are unavailable on this platform"
        ) from exc

    if cpu_seconds is not None:
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (cpu_seconds, cpu_seconds),
        )
    if memory_mb is not None:
        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_AS,
            (memory_bytes, memory_bytes),
        )
    if file_size_mb is not None:
        file_bytes = file_size_mb * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (file_bytes, file_bytes),
        )
    if open_files is not None:
        resource.setrlimit(
            resource.RLIMIT_NOFILE,
            (open_files, open_files),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-workflow-provider-sandbox-exec",
        add_help=False,
    )
    parser.add_argument("--cpu-seconds", type=_positive_int)
    parser.add_argument("--memory-mb", type=_positive_int)
    parser.add_argument("--file-size-mb", type=_positive_int)
    parser.add_argument("--open-files", type=_positive_int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise SystemExit("sandbox exec wrapper requires a command")

    _apply_limits(
        cpu_seconds=args.cpu_seconds,
        memory_mb=args.memory_mb,
        file_size_mb=args.file_size_mb,
        open_files=args.open_files,
    )
    os.execvpe(command[0], command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
