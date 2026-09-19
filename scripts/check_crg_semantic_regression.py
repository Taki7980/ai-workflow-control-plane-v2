from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


class CrgSemanticRegressionError(RuntimeError):
    pass


def _metric(container: Mapping[str, Any], key: str) -> float:
    raw = container.get(key)
    if raw is None:
        raise CrgSemanticRegressionError(f"missing metric: {key}")
    return float(raw)


def check_regression(
    baseline: Mapping[str, Any],
    report: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    if report.get("benchmark") != baseline.get("benchmark"):
        failures.append(
            "benchmark identity mismatch: "
            f"{report.get('benchmark')!r} != {baseline.get('benchmark')!r}"
        )

    expected_crg = str(baseline.get("crg_version") or "")
    actual_crg = str(report.get("crg_version_actual") or "")
    if expected_crg and expected_crg not in actual_crg:
        failures.append(
            f"CRG version mismatch: expected {expected_crg}, got {actual_crg}"
        )

    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        return failures + ["report summary missing"]

    for key, minimum in dict(baseline.get("minimums") or {}).items():
        actual = _metric(summary, str(key))
        if actual < float(minimum):
            failures.append(
                f"{key} regressed: {actual} < minimum {float(minimum)}"
            )

    for key, maximum in dict(baseline.get("maximums") or {}).items():
        actual = _metric(summary, str(key))
        if actual > float(maximum):
            failures.append(
                f"{key} regressed: {actual} > maximum {float(maximum)}"
            )

    categories = report.get("by_category")
    if not isinstance(categories, Mapping):
        failures.append("category summary missing")
        return failures

    for category, minimum in dict(
        baseline.get("category_minimum_recall") or {}
    ).items():
        row = categories.get(category)
        if not isinstance(row, Mapping):
            failures.append(f"category missing: {category}")
            continue
        actual = _metric(row, "mean_recall_at_k")
        if actual < float(minimum):
            failures.append(
                f"{category} recall regressed: "
                f"{actual} < minimum {float(minimum)}"
            )

    known = set(str(x) for x in baseline.get("known_misses") or [])
    case_ids = {
        str(row.get("case_id"))
        for row in report.get("cases", [])
        if isinstance(row, Mapping)
    }
    controls = report.get("controls")
    control_ids = set(controls) if isinstance(controls, Mapping) else set()
    unresolved = sorted(known - case_ids - control_ids)
    if unresolved:
        failures.append(
            "known-miss identities disappeared from benchmark: "
            + ", ".join(unresolved)
        )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail on material CRG semantic benchmark regression."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = check_regression(baseline, report)
    if failures:
        for failure in failures:
            print(f"CRG_SEMANTIC_REGRESSION: {failure}")
        return 1

    print(
        "CRG_SEMANTIC_REGRESSION_OK "
        + json.dumps(report["summary"], sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
