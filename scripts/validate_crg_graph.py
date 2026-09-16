from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_workflow.code_review_graph import (
    CRG_MIN_SCHEMA_VERSION,
    GraphValidationError,
    validate_graph_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Code Review Graph SQLite database."
    )
    parser.add_argument("graph", type=Path)
    parser.add_argument(
        "--minimum-schema",
        type=int,
        default=CRG_MIN_SCHEMA_VERSION,
    )
    args = parser.parse_args()

    try:
        summary = validate_graph_database(
            args.graph,
            minimum_schema_version=args.minimum_schema,
        )
    except GraphValidationError as exc:
        parser.error(str(exc))

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
