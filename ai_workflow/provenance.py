from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _canonical(value[k]) for k in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactReference:
    kind: str
    uri: str
    digest: str | None = None
    version: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class RunMetadata:
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
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    runtime: Mapping[str, str] = field(default_factory=lambda: {
        "python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform()
    })

    @classmethod
    def create(cls, **kwargs: Any) -> "RunMetadata":
        return cls(**kwargs)

    def reproducibility_key(self) -> str:
        return _digest({
            "schema_version": self.schema_version, "control_plane_version": self.control_plane_version,
            "workspace_fingerprint": self.workspace_fingerprint, "git_head": self.git_head,
            "changed_files_digest": self.changed_files_digest, "config_digest": self.config_digest,
            "retrieval_policy_version": self.retrieval_policy_version, "index_manifest_digest": self.index_manifest_digest,
            "provider_versions": self.provider_versions, "artifacts": [asdict(x) for x in self.artifacts], "runtime": self.runtime,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "run_id": self.run_id, "created_at": self.created_at,
            "control_plane_version": self.control_plane_version, "workspace_fingerprint": self.workspace_fingerprint,
            "git_head": self.git_head, "changed_files_digest": self.changed_files_digest, "config_digest": self.config_digest,
            "retrieval_policy_version": self.retrieval_policy_version, "index_manifest_digest": self.index_manifest_digest,
            "provider_versions": dict(self.provider_versions), "runtime": dict(self.runtime),
            "artifacts": [asdict(item) for item in self.artifacts], "reproducibility_key": self.reproducibility_key(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RunMetadata":
        return cls(
            schema_version=int(raw.get("schema_version", 1)), run_id=str(raw["run_id"]), created_at=str(raw["created_at"]),
            control_plane_version=str(raw["control_plane_version"]), workspace_fingerprint=str(raw["workspace_fingerprint"]),
            git_head=str(raw["git_head"]) if raw.get("git_head") is not None else None,
            changed_files_digest=str(raw["changed_files_digest"]), config_digest=str(raw["config_digest"]),
            retrieval_policy_version=str(raw["retrieval_policy_version"]), index_manifest_digest=str(raw["index_manifest_digest"]),
            provider_versions={str(k): str(v) for k, v in dict(raw.get("provider_versions") or {}).items()},
            artifacts=tuple(ArtifactReference(**dict(item)) for item in raw.get("artifacts", []) if isinstance(item, Mapping)),
            runtime={str(k): str(v) for k, v in dict(raw.get("runtime") or {}).items()},
        )


class RunStore(Protocol):
    def add(self, run: RunMetadata) -> None: ...
    def get(self, run_id: str) -> RunMetadata | None: ...
    def list(self, limit: int = 100) -> list[RunMetadata]: ...


class LocalRunStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        if not safe or safe != run_id:
            raise ValueError("invalid run_id")
        return self.directory / f"{safe}.json"

    def add(self, run: RunMetadata) -> None:
        path = self._path(run.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(run.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n")

    def get(self, run_id: str) -> RunMetadata | None:
        try:
            return RunMetadata.from_dict(json.loads(self._path(run_id).read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def list(self, limit: int = 100) -> list[RunMetadata]:
        if not self.directory.exists():
            return []
        rows: list[RunMetadata] = []
        for path in sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
            try:
                rows.append(RunMetadata.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if len(rows) >= max(0, int(limit)):
                break
        return rows


def config_digest(config: Mapping[str, Any]) -> str:
    return _digest(config)


def changed_files_digest(changed_files: tuple[str, ...] | list[str]) -> str:
    return _digest(sorted(str(item).replace("\\", "/") for item in changed_files))


def index_manifest_digest(root: Path) -> str:
    path = Path(root) / "ai-workspace" / "generated" / "index-state.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _digest({"missing": True})
    return _digest({"version": raw.get("version"), "files": raw.get("files", {})})


def git_head(root: Path) -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def provider_versions_from_config(config: Mapping[str, Any]) -> dict[str, str]:
    context = dict(config.get("context") or {})
    out: dict[str, str] = {}
    semantic = context.get("semantic")
    if isinstance(semantic, Mapping) and semantic.get("command"):
        out["semantic"] = str(semantic.get("version", "unknown"))
    external = context.get("external_retrievers")
    if isinstance(external, list):
        for index, item in enumerate(external):
            if isinstance(item, Mapping):
                out[str(item.get("name") or f"external_{index}")] = str(item.get("version", "unknown"))
    return dict(sorted(out.items()))


def to_openlineage(run: RunMetadata, *, job_name: str) -> dict[str, Any]:
    inputs, outputs = [], []
    for artifact in run.artifacts:
        entry = {"namespace": artifact.kind, "name": artifact.uri, "facets": {"aiWorkflow": {
            "_producer": "ai-workflow-control-plane", "digest": artifact.digest, "version": artifact.version, "role": artifact.role
        }}}
        (outputs if artifact.role and artifact.role.startswith("output") else inputs).append(entry)
    return {
        "eventType": "COMPLETE", "eventTime": run.created_at, "producer": "ai-workflow-control-plane",
        "run": {"runId": run.run_id, "facets": {"aiWorkflow": {"reproducibilityKey": run.reproducibility_key()}}},
        "job": {"namespace": "ai-workflow", "name": job_name}, "inputs": inputs, "outputs": outputs,
    }
