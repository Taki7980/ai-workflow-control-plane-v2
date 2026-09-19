from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uv_version() -> str:
    completed = subprocess.run(
        ["uv", "--version"],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def build_record(packages: list[str]) -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in sorted(set(packages)):
        versions[name] = importlib.metadata.version(name)

    lock = ROOT / "uv.lock"
    pyproject = ROOT / "pyproject.toml"
    if not lock.is_file():
        raise FileNotFoundError("uv.lock is required for toolchain recording")
    if not pyproject.is_file():
        raise FileNotFoundError("pyproject.toml is required for toolchain recording")

    return {
        "schema_version": 1,
        "source": {
            "repository": os.getenv("GITHUB_REPOSITORY"),
            "commit": os.getenv("GITHUB_SHA"),
            "ref": os.getenv("GITHUB_REF"),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "cache_tag": sys.implementation.cache_tag,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "resolver": {
            "uv": _uv_version(),
        },
        "inputs": {
            "pyproject_toml_sha256": _sha256(pyproject),
            "uv_lock_sha256": _sha256(lock),
        },
        "packages": versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record exact Python build/toolchain identity as JSON."
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        dest="packages",
        help="Installed distribution name to record. Repeat as needed.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="JSON output path.",
    )
    args = parser.parse_args()

    record = build_record(args.packages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
