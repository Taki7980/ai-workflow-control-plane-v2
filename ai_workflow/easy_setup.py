from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import setup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-workflow-setup",
        description="Connect AI Workflow to the current project without overwriting existing files.",
    )
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--project-name", help="optional display name; defaults to the directory name")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = setup(Path(args.root), args.project_name)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
