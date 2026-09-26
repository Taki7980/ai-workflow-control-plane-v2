from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
_ALLOWED_STATUS = {
    "implemented",
    "experimental",
    "external_activation",
    "conditional",
}
_ALLOWED_EVIDENCE_LEVELS = {
    "verified",
    "measured",
    "experimental",
    "external",
}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("capability evidence manifest must be a JSON object")
    return value


def _required_text(mapping: Mapping[str, Any], field: str, *, label: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must define non-empty {field}")
    return value.strip()


def _required_list(
    mapping: Mapping[str, Any],
    field: str,
    *,
    label: str,
    allow_empty: bool = False,
) -> list[Any]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{label} {field} must be a list")
    if not allow_empty and not value:
        raise ValueError(f"{label} {field} must not be empty")
    return value


def _validated_repo_path(root: Path, raw: Any, *, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} path must be a non-empty string")
    value = raw.strip().replace("\\", "/")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} path must stay repository-relative: {value}")
    resolved_root = root.resolve()
    resolved = (resolved_root / path).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"{label} path escapes repository root: {value}"
        ) from exc
    if not resolved.exists():
        raise ValueError(f"{label} path does not exist: {value}")
    return value


def validate_manifest(
    document: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"capability evidence schema_version must be {SCHEMA_VERSION}"
        )

    baseline = document.get("baseline")
    if not isinstance(baseline, Mapping):
        raise ValueError("capability evidence manifest must define baseline")
    _required_text(baseline, "repository", label="baseline")
    baseline_commit = _required_text(
        baseline,
        "commit",
        label="baseline",
    ).lower()
    if not _SHA40.fullmatch(baseline_commit):
        raise ValueError("baseline commit must be a 40-character Git SHA")
    _required_text(baseline, "date", label="baseline")

    raw_sources = document.get("research_sources")
    if not isinstance(raw_sources, list):
        raise ValueError("research_sources must be a list")
    source_ids: set[str] = set()
    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, Mapping):
            raise ValueError(f"research source {index} must be an object")
        label = f"research source {index}"
        source_id = _required_text(raw_source, "id", label=label)
        if source_id in source_ids:
            raise ValueError(f"duplicate research source id: {source_id}")
        source_ids.add(source_id)
        _required_text(raw_source, "kind", label=label)
        url = _required_text(raw_source, "url", label=label)
        if not url.startswith("https://"):
            raise ValueError(f"{label} url must use https")
        _required_text(raw_source, "scope", label=label)

    raw_capabilities = document.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise ValueError("capabilities must be a non-empty list")

    capability_ids: set[str] = set()
    status_counts: dict[str, int] = {}
    evidence_counts: dict[str, int] = {}
    checked_paths = 0

    for index, raw_capability in enumerate(raw_capabilities):
        if not isinstance(raw_capability, Mapping):
            raise ValueError(f"capability {index} must be an object")
        label = f"capability {index}"
        capability_id = _required_text(
            raw_capability,
            "id",
            label=label,
        )
        if capability_id in capability_ids:
            raise ValueError(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)

        _required_text(raw_capability, "claim", label=capability_id)
        _required_text(raw_capability, "scope", label=capability_id)

        status = _required_text(
            raw_capability,
            "status",
            label=capability_id,
        )
        if status not in _ALLOWED_STATUS:
            raise ValueError(
                f"{capability_id} has unsupported status: {status}"
            )
        status_counts[status] = status_counts.get(status, 0) + 1

        evidence_level = _required_text(
            raw_capability,
            "evidence_level",
            label=capability_id,
        )
        if evidence_level not in _ALLOWED_EVIDENCE_LEVELS:
            raise ValueError(
                f"{capability_id} has unsupported evidence_level: "
                f"{evidence_level}"
            )
        evidence_counts[evidence_level] = (
            evidence_counts.get(evidence_level, 0) + 1
        )

        production_default = raw_capability.get("production_default")
        if not isinstance(production_default, bool):
            raise ValueError(
                f"{capability_id} production_default must be boolean"
            )
        if status in {"experimental", "external_activation"} and production_default:
            raise ValueError(
                f"{capability_id} cannot be production-default while {status}"
            )
        if status == "experimental" and evidence_level != "experimental":
            raise ValueError(
                f"{capability_id} experimental status requires "
                "experimental evidence_level"
            )
        if status == "implemented" and evidence_level == "experimental":
            raise ValueError(
                f"{capability_id} implemented status cannot use "
                "experimental evidence_level"
            )

        implementation = _required_list(
            raw_capability,
            "implementation",
            label=capability_id,
        )
        verification = _required_list(
            raw_capability,
            "verification",
            label=capability_id,
        )
        benchmarks = _required_list(
            raw_capability,
            "benchmarks",
            label=capability_id,
            allow_empty=True,
        )
        limitations = _required_list(
            raw_capability,
            "limitations",
            label=capability_id,
        )
        if any(
            not isinstance(item, str) or not item.strip()
            for item in limitations
        ):
            raise ValueError(
                f"{capability_id} limitations must contain non-empty strings"
            )

        validated_verification: list[str] = []
        for field_name, values in (
            ("implementation", implementation),
            ("verification", verification),
            ("benchmarks", benchmarks),
        ):
            for raw_path in values:
                path = _validated_repo_path(
                    root,
                    raw_path,
                    label=f"{capability_id} {field_name}",
                )
                checked_paths += 1
                if field_name == "verification":
                    validated_verification.append(path)

        if not any(
            path.startswith(("tests/", "security_tests/", ".github/workflows/"))
            for path in validated_verification
        ):
            raise ValueError(
                f"{capability_id} verification must cite a test or CI workflow"
            )

        if evidence_level == "measured" and not benchmarks:
            raise ValueError(
                f"{capability_id} measured evidence requires benchmark paths"
            )

        research_refs = _required_list(
            raw_capability,
            "research_refs",
            label=capability_id,
            allow_empty=True,
        )
        for raw_ref in research_refs:
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise ValueError(
                    f"{capability_id} research_refs must contain strings"
                )
            if raw_ref not in source_ids:
                raise ValueError(
                    f"{capability_id} references unknown research source: "
                    f"{raw_ref}"
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_commit": baseline_commit,
        "capabilities": len(capability_ids),
        "research_sources": len(source_ids),
        "checked_paths": checked_paths,
        "status_counts": dict(sorted(status_counts.items())),
        "evidence_level_counts": dict(sorted(evidence_counts.items())),
    }


def load_and_validate_manifest(
    manifest_path: Path,
    *,
    root: Path,
) -> dict[str, Any]:
    return validate_manifest(load_manifest(manifest_path), root=root)
