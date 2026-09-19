from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


SANDBOX_MODES = {"off", "preferred", "required"}
SANDBOX_BACKENDS = {"auto", "bubblewrap"}
NETWORK_POLICIES = {"host", "deny"}

MAX_CPU_SECONDS = 86_400
MAX_MEMORY_MB = 1_048_576
MAX_FILE_SIZE_MB = 1_048_576
MAX_OPEN_FILES = 1_000_000


class SandboxUnavailableError(RuntimeError):
    """A requested provider sandbox policy cannot be enforced."""


def _bounded_positive_int(
    value: Any,
    *,
    field_name: str,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"sandbox {field_name} must be an integer")
    if value < 1 or value > maximum:
        raise ValueError(
            f"sandbox {field_name} must be between 1 and {maximum}"
        )
    return value


@dataclass(frozen=True)
class ResourceLimits:
    """Per-process resource limits enforced by a dedicated exec wrapper."""

    cpu_seconds: int | None = None
    memory_mb: int | None = None
    file_size_mb: int | None = None
    open_files: int | None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> "ResourceLimits":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ValueError("sandbox limits must be an object")
        known = {
            "cpu_seconds",
            "memory_mb",
            "file_size_mb",
            "open_files",
        }
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(
                "unknown sandbox limit fields: " + ", ".join(unknown)
            )
        return cls(
            cpu_seconds=_bounded_positive_int(
                raw.get("cpu_seconds"),
                field_name="cpu_seconds",
                maximum=MAX_CPU_SECONDS,
            ),
            memory_mb=_bounded_positive_int(
                raw.get("memory_mb"),
                field_name="memory_mb",
                maximum=MAX_MEMORY_MB,
            ),
            file_size_mb=_bounded_positive_int(
                raw.get("file_size_mb"),
                field_name="file_size_mb",
                maximum=MAX_FILE_SIZE_MB,
            ),
            open_files=_bounded_positive_int(
                raw.get("open_files"),
                field_name="open_files",
                maximum=MAX_OPEN_FILES,
            ),
        )

    @property
    def any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.cpu_seconds,
                self.memory_mb,
                self.file_size_mb,
                self.open_files,
            )
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "file_size_mb": self.file_size_mb,
            "open_files": self.open_files,
        }


@dataclass(frozen=True)
class SandboxPolicy:
    """Trusted-registry-owned provider sandbox policy."""

    mode: str = "off"
    backend: str = "auto"
    network: str = "host"
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self) -> None:
        mode = str(self.mode).strip().lower()
        backend = str(self.backend).strip().lower()
        network = str(self.network).strip().lower()
        if mode not in SANDBOX_MODES:
            raise ValueError(
                f"sandbox mode must be one of {sorted(SANDBOX_MODES)}"
            )
        if backend not in SANDBOX_BACKENDS:
            raise ValueError(
                f"sandbox backend must be one of {sorted(SANDBOX_BACKENDS)}"
            )
        if network not in NETWORK_POLICIES:
            raise ValueError(
                f"sandbox network must be one of {sorted(NETWORK_POLICIES)}"
            )
        if not isinstance(self.limits, ResourceLimits):
            raise ValueError("sandbox limits must be ResourceLimits")
        if mode == "off" and (
            network != "host" or self.limits.any
        ):
            raise ValueError(
                "sandbox mode=off cannot enforce network or resource limits"
            )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "network", network)

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any] | None,
    ) -> "SandboxPolicy":
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ValueError("provider sandbox must be an object")
        known = {"mode", "backend", "network", "limits"}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(
                "unknown provider sandbox fields: " + ", ".join(unknown)
            )
        return cls(
            mode=str(raw.get("mode") or "off"),
            backend=str(raw.get("backend") or "auto"),
            network=str(raw.get("network") or "host"),
            limits=ResourceLimits.from_mapping(raw.get("limits")),
        )

    @property
    def must_enforce(self) -> bool:
        return (
            self.mode == "required"
            or self.network == "deny"
            or self.limits.any
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "backend": self.backend,
            "network": self.network,
            "limits": self.limits.to_dict(),
        }


@dataclass(frozen=True)
class SandboxPlan:
    command: tuple[str, ...]
    sandboxed: bool
    backend: str | None
    mode: str
    network: str
    resource_limits_enforced: bool
    fallback_reason: str | None = None


@functools.lru_cache(maxsize=4)
def _bubblewrap_probe(path: str, network: str) -> bool:
    """Verify the backend can establish the namespaces PR-17 depends on."""

    true_path = shutil.which("true")
    if not true_path:
        return False
    command = [
        path,
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    if network == "deny":
        command.append("--unshare-net")
    command.append(str(Path(true_path).resolve()))
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _resolve_bubblewrap(network: str = "host") -> Path | None:
    if not sys.platform.startswith("linux"):
        return None
    raw = shutil.which("bwrap")
    if not raw:
        return None
    path = Path(raw).resolve()
    if not path.is_file():
        return None
    if not _bubblewrap_probe(str(path), network):
        return None
    return path


def _limit_wrapper(
    command: Sequence[str],
    limits: ResourceLimits,
) -> tuple[str, ...]:
    if not limits.any:
        return tuple(command)
    args = [
        sys.executable,
        "-m",
        "ai_workflow.provider_sandbox_exec",
    ]
    if limits.cpu_seconds is not None:
        args.extend(["--cpu-seconds", str(limits.cpu_seconds)])
    if limits.memory_mb is not None:
        args.extend(["--memory-mb", str(limits.memory_mb)])
    if limits.file_size_mb is not None:
        args.extend(["--file-size-mb", str(limits.file_size_mb)])
    if limits.open_files is not None:
        args.extend(["--open-files", str(limits.open_files)])
    args.append("--")
    args.extend(command)
    return tuple(args)


def _dedupe_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw).resolve()
        key = os.fspath(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)


def build_sandbox_plan(
    policy: SandboxPolicy,
    command: Sequence[str],
    *,
    cwd: Path,
    writable_paths: Sequence[Path],
) -> SandboxPlan:
    """Build the exact OS sandbox command or fail closed.

    The bubblewrap backend makes the host root read-only, permits writes only
    to explicit runtime paths, optionally removes network access, and delegates
    resource limits to a small exec wrapper rather than unsafe preexec_fn code.
    """

    raw_command = tuple(str(part) for part in command)
    if not raw_command:
        raise ValueError("sandbox command must not be empty")

    if policy.mode == "off":
        return SandboxPlan(
            command=raw_command,
            sandboxed=False,
            backend=None,
            mode=policy.mode,
            network=policy.network,
            resource_limits_enforced=False,
        )

    backend_path: Path | None = None
    if policy.backend in {"auto", "bubblewrap"}:
        backend_path = _resolve_bubblewrap(policy.network)

    if backend_path is None:
        if policy.must_enforce:
            raise SandboxUnavailableError(
                "provider sandbox policy requires an available enforcing backend"
            )
        return SandboxPlan(
            command=raw_command,
            sandboxed=False,
            backend=None,
            mode=policy.mode,
            network=policy.network,
            resource_limits_enforced=False,
            fallback_reason="backend_unavailable",
        )

    inner = _limit_wrapper(raw_command, policy.limits)
    args: list[str] = [
        str(backend_path),
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    if policy.network == "deny":
        args.append("--unshare-net")

    for writable in _dedupe_paths(writable_paths):
        if writable.exists():
            args.extend(["--bind", str(writable), str(writable)])

    args.extend(["--chdir", str(Path(cwd).resolve())])
    args.extend(inner)

    return SandboxPlan(
        command=tuple(args),
        sandboxed=True,
        backend="bubblewrap",
        mode=policy.mode,
        network=policy.network,
        resource_limits_enforced=policy.limits.any,
    )
