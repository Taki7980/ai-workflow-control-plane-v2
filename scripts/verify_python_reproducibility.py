from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


_ALLOWED_SUFFIXES = (".whl", ".tar.gz")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distribution_files(directory: Path) -> dict[str, Path]:
    root = directory.resolve()
    if not root.is_dir():
        raise ValueError(f"distribution directory does not exist: {directory}")

    files: dict[str, Path] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.is_symlink():
            raise ValueError(f"distribution artifact must not be a symlink: {path.name}")
        if not path.is_file():
            continue
        if not path.name.endswith(_ALLOWED_SUFFIXES):
            raise ValueError(
                f"unexpected file in distribution directory: {path.name}"
            )
        files[path.name] = path

    if not any(name.endswith(".whl") for name in files):
        raise ValueError("distribution directory must contain a wheel")
    if not any(name.endswith(".tar.gz") for name in files):
        raise ValueError("distribution directory must contain an sdist")
    return files


def compare_distribution_directories(
    candidate_a: Path,
    candidate_b: Path,
    *,
    source_date_epoch: int,
) -> dict[str, Any]:
    if source_date_epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be non-negative")

    first = _distribution_files(candidate_a)
    second = _distribution_files(candidate_b)
    names_a = set(first)
    names_b = set(second)

    only_a = sorted(names_a - names_b)
    only_b = sorted(names_b - names_a)
    artifacts: list[dict[str, Any]] = []
    mismatched: list[str] = []

    for name in sorted(names_a & names_b):
        digest_a = _sha256(first[name])
        digest_b = _sha256(second[name])
        size_a = first[name].stat().st_size
        size_b = second[name].stat().st_size
        match = digest_a == digest_b and size_a == size_b
        if not match:
            mismatched.append(name)
        artifacts.append(
            {
                "name": name,
                "sha256": digest_a,
                "size": size_a,
                "candidate_b_sha256": digest_b,
                "candidate_b_size": size_b,
                "match": match,
            }
        )

    reproducible = not only_a and not only_b and not mismatched
    return {
        "schema_version": 1,
        "reproducible": reproducible,
        "source_date_epoch": source_date_epoch,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "only_candidate_a": only_a,
        "only_candidate_b": only_b,
        "digest_mismatches": mismatched,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two independently built Python distribution directories "
            "and emit machine-readable reproducibility evidence."
        )
    )
    parser.add_argument("--candidate-a", type=Path, required=True)
    parser.add_argument("--candidate-b", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = compare_distribution_directories(
        args.candidate_a,
        args.candidate_b,
        source_date_epoch=args.source_date_epoch,
    )
    _write_json(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["reproducible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
