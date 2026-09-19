from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crg_semantic_benchmark import (  # noqa: E402
    run_crg_semantic_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen CRG semantic golden benchmark."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "benchmarks" / "crg-semantic-v1" / "fixture",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "benchmarks" / "crg-semantic-v1" / "cases.json",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_crg_semantic_benchmark(
        fixture=args.fixture,
        cases_path=args.cases,
        limit=max(1, args.limit),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
