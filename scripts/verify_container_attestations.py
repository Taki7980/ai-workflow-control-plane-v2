from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUTS_PATH = ROOT / "packaging" / "container" / "inputs.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialized(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest_present(serialized: str, *digests: str) -> bool:
    for digest in digests:
        algorithm, value = digest.split(":", 1)
        if digest in serialized or value in serialized:
            return True
        if f'"{algorithm}":"{value}"' in serialized:
            return True
    return False


def verify_provenance(provenance: Any, inputs: dict[str, Any]) -> None:
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("container provenance must be a non-empty JSON object")

    raw = _serialized(provenance)
    for name in ("python_base", "uv_image"):
        material = inputs[name]
        if not _digest_present(
            raw,
            material["index_digest"],
            material["linux_amd64_digest"],
        ):
            raise ValueError(
                f"container provenance does not record the pinned {name} digest"
            )

    if "slsa" not in raw.lower() and "resolveddependencies" not in raw.lower():
        raise ValueError("container provenance does not look like SLSA provenance")


def verify_sbom(sbom: Any, inputs: dict[str, Any]) -> None:
    if not isinstance(sbom, (dict, list)) or not sbom:
        raise ValueError("container SBOM must be non-empty JSON")

    raw = _serialized(sbom)
    if "spdx" not in raw.lower():
        raise ValueError("container SBOM does not look like SPDX data")

    for package, version in inputs["runtime_packages"].items():
        if package not in raw:
            raise ValueError(f"container SBOM is missing runtime package {package}")
        if version not in raw:
            raise ValueError(
                f"container SBOM is missing locked {package} version {version}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify BuildKit provenance and SBOM against locked container inputs."
    )
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument(
        "--inputs",
        type=Path,
        default=INPUTS_PATH,
        help="Container input manifest (default: packaging/container/inputs.json).",
    )
    args = parser.parse_args()

    inputs = _load(args.inputs)
    verify_provenance(_load(args.provenance), inputs)
    verify_sbom(_load(args.sbom), inputs)

    print(
        json.dumps(
            {
                "status": "ok",
                "python_base": inputs["python_base"]["index_digest"],
                "uv_image": inputs["uv_image"]["index_digest"],
                "debian_snapshot": inputs["debian_snapshot"],
                "runtime_packages": inputs["runtime_packages"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
