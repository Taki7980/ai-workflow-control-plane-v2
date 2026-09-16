from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ai_workflow.repository_hygiene import repository_hygiene


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the tracked tree for generated or machine-local artifacts."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Git repository root to inspect (default: current directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the machine-readable hygiene result.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = repository_hygiene(Path(args.root))

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif not result["applicable"]:
        print("Repository hygiene: not applicable (not a Git repository)")
    elif result["clean"] and result["local_state_ignored"]:
        print(
            "Repository hygiene: clean "
            f"({result['tracked_files']} tracked files)"
        )
    else:
        print("Repository hygiene: FAILED")
        if result["tracked_forbidden"]:
            print(
                "Forbidden tracked paths: "
                + ", ".join(result["tracked_forbidden"])
            )
        if result["ignored_tracked"]:
            print(
                "Ignored paths still tracked: "
                + ", ".join(result["ignored_tracked"])
            )
        if not result["local_state_ignored"]:
            print(
                "Machine-local AI Workflow state is not fully ignored."
            )

    if not result["applicable"]:
        return 0
    return int(
        not (
            result["clean"]
            and result["local_state_ignored"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
