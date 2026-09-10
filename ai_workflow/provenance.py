from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _runtime_info() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }


@dataclass(frozen=True)
class ArtifactReference:
    """External model/dataset/artifact identity without a runtime dependency."""

    kind: str
    uri: str
    digest: str | None = None
    version: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class RunMetadata:
    """Immutable metadata required to explain or reproduce a prepared run."""

    control_plane_version: str
    workspace_fingerprint: str
    git_head: str | None
    changed_files_digest: str
    config_digest: str
    retrieval_policy_version: str
    index_manifest_digest: str
    provider_versions: Mapping[str, str]
    artifacts: tuple[ArtifactReference, ...] = ()
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: int = 1
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    runtime: Mapping[str, str] = field(default_factory=_runtime_info)

    @classmethod
    def create(cls, **kwargs: Any) -> RunMetadata:
        return cls(**kwargs)

    def reproducibility_key(self) -> str:
        return _digest(
            {
                "schema_version": self.schema_version,
                "control_plane_version": self.control_plane_version,
                "workspace_fingerprint": self.workspace_fingerprint,
                "git_head": self.git_head,
                "changed_files_digest": self.changed_files_digest,
                "config_digest": self.config_digest,
                "retrieval_policy_version": self.retrieval_policy_version,
                "index_manifest_digest": self.index_manifest_digest,
                "provider_versions": self.provider_versions,
                "artifacts": [asdict(item) for item in self.artifacts],
                "runtime": self.runtime,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "control_plane_version": self.control_plane_version,
            "workspace_fingerprint": self.workspace_fingerprint,
            "git_head": self.git_head,
            "changed_files_digest": self.changed_files_digest,
            "config_digest": self.config_digest,
            "retrieval_policy_version": self.retrieval_policy_version,
            "index_manifest_digest": self.index_manifest_digest,
            "provider_versions": dict(self.provider_versions),
            "runtime": dict(self.runtime),
            "artifacts": [asdict(item) for item in self.artifacts],
            "reproducibility_key": self.reproducibility_key(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> RunMetadata:
        provider_raw = raw.get("provider_versions")
        provider_versions = (
            {str(key): str(value) for key, value in provider_raw.items()}
            if isinstance(provider_raw, Mapping)
            else {}
        )
        runtime_raw = raw.get("runtime")
        runtime = (
            {str(key): str(value) for key, value in runtime_raw.items()}
            if isinstance(runtime_raw, Mapping)
            else {}
        )
        artifacts_raw = raw.get("artifacts")
        artifacts: list[ArtifactReference] = []
        if isinstance(artifacts_raw, list):
            for item in artifacts_raw:
                if not isinstance(item, Mapping):
                    continue
                artifacts.append(
                    ArtifactReference(
                        kind=str(item.get("kind", "artifact")),
                        uri=str(item.get("uri", "")),
                        digest=(
                            str(item["digest"])
                            if item.get("digest") is not None
                            else None
                        ),
                        version=(
                            str(item["version"])
                            if item.get("version") is not None
                            else None
                        ),
                        role=(
                            str(item["role"])
                            if item.get("role") is not None
                            else None
                        ),
                    )
                )
        return cls(
            schema_version=int(raw.get("schema_version", 1)),
            run_id=str(raw["run_id"]),
            created_at=str(raw["created_at"]),
            control_plane_version=str(raw["control_plane_version"]),
            workspace_fingerprint=str(raw["workspace_fingerprint"]),
            git_head=(
                str(raw["git_head"])
                if raw.get("git_head") is not None
                else None
            ),
            changed_files_digest=str(raw["changed_files_digest"]),
            config_digest=str(raw["config_digest"]),
            retrieval_policy_version=str(raw["retrieval_policy_version"]),
            index_manifest_digest=str(raw["index_manifest_digest"]),
            provider_versions=provider_versions,
            artifacts=tuple(artifacts),
            runtime=runtime,
        )


class RunStore(Protocol):
    def add(self, run: RunMetadata) -> None:
        ...

    def get(self, run_id: str) -> RunMetadata | None:
        ...

    def list(self, limit: int = 100) -> list[RunMetadata]:
        ...


class LocalRunStore:
    """One immutable JSON document per run; existing run IDs are never replaced."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, run_id: str) -> Path:
        safe = "".join(
            char for char in run_id if char.isalnum() or char in "-_"
        )
        if not safe or safe != run_id:
            raise ValueError("invalid run_id")
        return self.directory / f"{safe}.json"

    def add(self, run: RunMetadata) -> None:
        path = self._path(run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            run.to_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(payload + "\n")
            handle.flush()

    def get(self, run_id: str) -> RunMetadata | None:
        try:
            raw = json.loads(self._path(run_id).read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                return None
            return RunMetadata.from_dict(raw)
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

    def list(self, limit: int = 100) -> list[RunMetadata]:
        if not self.directory.exists() or limit <= 0:
            return []
        try:
            paths = sorted(
                self.directory.glob("*.json"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError:
            return []
        rows: list[RunMetadata] = []
        for path in paths:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, Mapping):
                    continue
                rows.append(RunMetadata.from_dict(raw))
            except (
                OSError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
            if len(rows) >= limit:
                break
        return rows


def config_digest(config: Mapping[str, Any]) -> str:
    return _digest(config)


def changed_files_digest(changed_files: tuple[str, ...] | list[str]) -> str:
    normalized = sorted(str(item).replace("\\", "/") for item in changed_files)
    return _digest(normalized)


def index_manifest_digest(root: Path) -> str:
    path = Path(root) / "ai-workspace" / "generated" / "index-state.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _digest({"missing": True})
    if not isinstance(raw, Mapping):
        return _digest({"invalid": True})
    return _digest(
        {
            "version": raw.get("version"),
            "files": raw.get("files", {}),
        }
    )


def git_head(root: Path) -> str | None:
    try:
        process = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = process.stdout.strip()
    return value if process.returncode == 0 and value else None


def provider_versions_from_config(
    config: Mapping[str, Any],
) -> dict[str, str]:
    context_raw = config.get("context")
    context = context_raw if isinstance(context_raw, Mapping) else {}
    versions: dict[str, str] = {}

    semantic = context.get("semantic")
    if isinstance(semantic, Mapping) and semantic.get("command"):
        versions["semantic"] = str(semantic.get("version", "unknown"))

    external = context.get("external_retrievers")
    if isinstance(external, list):
        for index, item in enumerate(external):
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or f"external_{index}")
            versions[name] = str(item.get("version", "unknown"))
    return dict(sorted(versions.items()))


def to_openlineage(run: RunMetadata, *, job_name: str) -> dict[str, Any]:
    """Return an OpenLineage-shaped dictionary without importing an SDK."""

    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for artifact in run.artifacts:
        entry = {
            "namespace": artifact.kind,
            "name": artifact.uri,
            "facets": {
                "aiWorkflow": {
                    "_producer": "ai-workflow-control-plane",
                    "digest": artifact.digest,
                    "version": artifact.version,
                    "role": artifact.role,
                }
            },
        }
        destination = (
            outputs
            if artifact.role and artifact.role.startswith("output")
            else inputs
        )
        destination.append(entry)
    return {
        "eventType": "COMPLETE",
        "eventTime": run.created_at,
        "producer": "ai-workflow-control-plane",
        "run": {
            "runId": run.run_id,
            "facets": {
                "aiWorkflow": {
                    "reproducibilityKey": run.reproducibility_key()
                }
            },
        },
        "job": {"namespace": "ai-workflow", "name": job_name},
        "inputs": inputs,
        "outputs": outputs,
    }
