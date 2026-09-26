from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ai_workflow.capability_evidence import load_and_validate_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the machine-readable capability-to-evidence manifest."
        )
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--manifest",
        default="evidence/capabilities.json",
        help=(
            "Manifest path relative to --root "
            "(default: evidence/capabilities.json)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the validation summary as JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve()
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = root / manifest

    try:
        summary = load_and_validate_manifest(manifest, root=root)
    except (OSError, ValueError) as exc:
        print(f"Capability evidence: FAILED: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            "Capability evidence: clean "
            f"({summary['capabilities']} capabilities, "
            f"{summary['checked_paths']} evidence paths)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
