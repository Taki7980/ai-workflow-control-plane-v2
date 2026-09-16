from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .execution_semantics import ProviderSemantics
from .models import ContextItem
from .path_policy import confine_metadata_paths
from .retrieval_contracts import ProviderResult, RetrievalRequest


DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024


def _provider_process_group_kwargs() -> dict[str, Any]:
    """Launch each provider in an isolated OS process group/session."""

    if os.name == "nt":
        return {
            "creationflags": int(
                getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0x00000200,
                )
            )
        }
    return {"start_new_session": True}


def _terminate_provider_tree(proc: Any) -> None:
    """Terminate a provider and any descendants without invoking a shell."""

    if getattr(proc, "returncode", None) is not None:
        return

    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "taskkill",
                    "/PID",
                    str(proc.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except OSError:
            pass

    try:
        proc.kill()
    except OSError:
        pass


SAFE_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
}


@dataclass(frozen=True)
class CommandProviderSpec:
    name: str
    command: tuple[str, ...]
    timeout_seconds: float = 8.0
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES
    intents: tuple[str, ...] = ("all",)
    env_allowlist: tuple[str, ...] = ()
    executable_trust: str = "configured_local_executable"
    executable_sha256: str | None = None
    neutral_cwd: bool = False
    version: str = "unknown"
    semantics: ProviderSemantics = field(default_factory=ProviderSemantics)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("provider name must not be blank")
        if not self.command or any(not str(part) for part in self.command):
            raise ValueError(f"provider {self.name!r} command must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError(
                f"provider {self.name!r} timeout_seconds must be > 0"
            )
        if self.max_output_bytes <= 0:
            raise ValueError(
                f"provider {self.name!r} max_output_bytes must be > 0"
            )
        if self.max_stderr_bytes <= 0:
            raise ValueError(
                f"provider {self.name!r} max_stderr_bytes must be > 0"
            )
        if self.executable_sha256 is not None:
            digest = self.executable_sha256.strip().lower()
            if digest.startswith("sha256:"):
                digest = digest.removeprefix("sha256:")
            if len(digest) != 64 or any(
                ch not in "0123456789abcdef" for ch in digest
            ):
                raise ValueError(
                    f"provider {self.name!r} executable_sha256 must be a SHA-256 digest"
                )
            object.__setattr__(self, "executable_sha256", digest)
        if not self.version.strip():
            raise ValueError(f"provider {self.name!r} version must not be blank")


def build_provider_env(allowed_keys: Iterable[str] = ()) -> dict[str, str]:
    """Build the subprocess environment without inheriting arbitrary secrets."""

    keys = set(SAFE_ENV_KEYS)
    keys.update(str(key) for key in allowed_keys if str(key).strip())
    return {key: os.environ[key] for key in keys if key in os.environ}


def command_provider_spec(
    raw: Mapping[str, Any],
    default_name: str = "provider",
) -> CommandProviderSpec:
    command = raw.get("command", "")
    if isinstance(command, str):
        argv = tuple(shlex.split(command))
    elif isinstance(command, (list, tuple)):
        argv = tuple(str(part) for part in command)
    else:
        raise ValueError("provider command must be a string or argv list")

    intents = raw.get("intents", ["all"])
    if isinstance(intents, str):
        intents = [intents]
    if not isinstance(intents, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in intents
    ):
        raise ValueError("provider intents must be a list of non-empty strings")

    env_allowlist = raw.get("env_allowlist", [])
    if isinstance(env_allowlist, str):
        env_allowlist = [env_allowlist]
    if not isinstance(env_allowlist, (list, tuple)) or not all(
        isinstance(item, str) and item.strip() for item in env_allowlist
    ):
        raise ValueError(
            "provider env_allowlist must be a list of non-empty strings"
        )

    semantics_raw = raw.get("semantics")
    if semantics_raw is not None and not isinstance(semantics_raw, Mapping):
        raise ValueError("provider semantics must be an object")

    neutral_cwd = raw.get("neutral_cwd", False)
    if not isinstance(neutral_cwd, bool):
        raise ValueError("provider neutral_cwd must be a boolean")

    executable_sha256 = str(
        raw.get("executable_sha256") or raw.get("sha256") or ""
    ).strip().lower()
    if executable_sha256.startswith("sha256:"):
        executable_sha256 = executable_sha256.removeprefix("sha256:")

    return CommandProviderSpec(
        name=str(raw.get("name") or default_name),
        command=argv,
        timeout_seconds=float(raw.get("timeout_seconds", 8)),
        max_output_bytes=int(
            raw.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES)
        ),
        max_stderr_bytes=int(
            raw.get("max_stderr_bytes", DEFAULT_MAX_STDERR_BYTES)
        ),
        intents=tuple(intents),
        env_allowlist=tuple(env_allowlist),
        executable_sha256=executable_sha256 or None,
        neutral_cwd=neutral_cwd,
        version=str(raw.get("version") or "unknown"),
        semantics=ProviderSemantics.from_mapping(semantics_raw),
    )


def _request_payload(request: RetrievalRequest) -> bytes:
    payload = {
        "query": request.query,
        "root": str(request.root.resolve()),
        "limit": request.limit,
        "intent": request.intent,
        "changed_files": list(request.changed_files),
        "metadata": dict(request.metadata),
    }
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def _bounded_reader(
    proc: subprocess.Popen[bytes],
    limit: int,
    output: bytearray,
    exceeded: threading.Event,
) -> None:
    assert proc.stdout is not None
    try:
        while True:
            remaining = limit - len(output)
            chunk = proc.stdout.read(min(65536, max(1, remaining + 1)))
            if not chunk:
                return
            if len(chunk) > remaining:
                output.extend(chunk[: max(0, remaining)])
                exceeded.set()
                _terminate_provider_tree(proc)
                return
            output.extend(chunk)
    except OSError:
        return


async def _bounded_async_reader(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    output = bytearray()
    while True:
        remaining = limit - len(output)
        chunk = await stream.read(min(65536, max(1, remaining + 1)))
        if not chunk:
            return bytes(output), False
        if len(chunk) > remaining:
            output.extend(chunk[: max(0, remaining)])
            return bytes(output), True
        output.extend(chunk)


def _parse_records(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "provider returned invalid JSON/JSONL payload"
                ) from exc
            if not isinstance(row, dict):
                raise ValueError("provider JSONL rows must be objects") from None
            rows.append(row)
        if not rows and raw.strip():
            raise ValueError("provider returned invalid JSON/JSONL payload") from None
        return rows

    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        raise ValueError(
            "provider payload must be a JSON array or an object with an items array"
        )
    return [row for row in payload if isinstance(row, dict)]


def _score(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _context_items(
    root: Path,
    records: list[dict[str, Any]],
    source: str,
    limit: int,
    provider_name: str,
    provider_trust: str,
    metadata_defaults: Mapping[str, Any] | None,
) -> tuple[ContextItem, ...]:
    items: list[ContextItem] = []
    defaults = dict(metadata_defaults or {})
    for record in records:
        text = str(
            record.get("text") or record.get("content") or ""
        ).strip()
        if not text:
            continue
        metadata = (
            dict(record.get("metadata") or {})
            if isinstance(record.get("metadata"), dict)
            else {}
        )
        for key in (
            "path",
            "file",
            "line",
            "end_line",
            "symbol",
            "kind",
            "language",
        ):
            if key in record:
                metadata[key] = record[key]
        metadata.update(defaults)
        metadata["provider"] = provider_name
        metadata["provider_trust"] = provider_trust
        metadata["trust"] = "untrusted_repository_content"
        metadata = confine_metadata_paths(root, metadata)
        provenance = (
            dict(record.get("provenance") or {})
            if isinstance(record.get("provenance"), dict)
            else {}
        )
        provenance["provider"] = provider_name
        provenance["trust"] = "untrusted_repository_content"
        items.append(
            ContextItem(
                source=source,
                text=text,
                score=_score(record.get("score", 0.0)),
                stale=bool(record.get("stale", False)),
                metadata=metadata,
                provenance=provenance,
            )
        )
    items.sort(key=lambda item: -item.score)
    return tuple(items[:limit])


def _result_from_bytes(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
    source: str,
    metadata_defaults: Mapping[str, Any] | None,
    output: bytes,
    latency_ms: float,
    returncode: int | None,
) -> ProviderResult:
    text = output.decode("utf-8", errors="replace")
    if not text.strip():
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error="provider returned an empty payload",
            error_kind="empty_output",
            returncode=returncode,
        )
    try:
        records = _parse_records(text)
    except ValueError as exc:
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=str(exc),
            error_kind="invalid_payload",
            returncode=returncode,
        )
    return ProviderResult(
        provider=spec.name,
        items=_context_items(
            request.root,
            records,
            source,
            request.limit,
            spec.name,
            spec.executable_trust,
            metadata_defaults,
        ),
        latency_ms=latency_ms,
        returncode=returncode,
    )


class ProviderTrustError(ValueError):
    """Trusted provider identity changed or violates launch policy."""


def _is_within(root: Path, candidate: Path) -> bool:
    root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_provider_executable(
    spec: CommandProviderSpec,
    root: Path,
) -> Path:
    configured = Path(spec.command[0]).expanduser()
    if spec.executable_trust != "trusted_registry_digest":
        return configured
    if not configured.is_absolute():
        raise ProviderTrustError(
            "trusted provider executable must remain an absolute path"
        )
    if configured.is_symlink():
        raise ProviderTrustError(
            "trusted provider executable path may not be a symlink"
        )
    try:
        resolved = configured.resolve(strict=True)
    except OSError as exc:
        raise ProviderTrustError(
            "trusted provider executable no longer exists"
        ) from exc
    if not resolved.is_file():
        raise ProviderTrustError(
            "trusted provider executable is no longer a regular file"
        )
    if _is_within(root, resolved):
        raise ProviderTrustError(
            "trusted provider executable may not move inside the repository"
        )
    expected = spec.executable_sha256
    if not expected:
        raise ProviderTrustError(
            "trusted provider executable is missing its pinned digest"
        )
    actual = _sha256_file(resolved)
    if not hmac.compare_digest(actual, expected):
        raise ProviderTrustError(
            "trusted provider executable digest mismatch at launch"
        )
    return resolved


def _verified_command(
    spec: CommandProviderSpec,
    root: Path,
) -> tuple[str, ...]:
    if spec.executable_trust != "trusted_registry_digest":
        return spec.command
    executable = verify_provider_executable(spec, root)
    return (str(executable), *spec.command[1:])


def _legacy_provider_cwd(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
) -> Path:
    if spec.executable_trust == "trusted_registry_digest":
        try:
            return Path(spec.command[0]).resolve(strict=True).parent
        except OSError:
            return Path(spec.command[0]).expanduser().resolve().parent
    return request.root


@contextmanager
def _provider_launch_cwd(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
):
    if spec.neutral_cwd:
        with tempfile.TemporaryDirectory(
            prefix="ai-workflow-provider-",
        ) as td:
            yield Path(td)
        return
    yield _legacy_provider_cwd(spec, request)


def _bounded_tail_reader(
    stream: Any,
    limit: int,
    output: bytearray,
    truncated: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            if len(chunk) >= limit:
                output[:] = chunk[-limit:]
                truncated.set()
                continue
            overflow = len(output) + len(chunk) - limit
            if overflow > 0:
                del output[:overflow]
                truncated.set()
            output.extend(chunk)
    except OSError:
        return


async def _bounded_async_tail_reader(
    stream: asyncio.StreamReader,
    limit: int,
) -> tuple[bytes, bool]:
    output = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(output), truncated
        if len(chunk) >= limit:
            output[:] = chunk[-limit:]
            truncated = True
            continue
        overflow = len(output) + len(chunk) - limit
        if overflow > 0:
            del output[:overflow]
            truncated = True
        output.extend(chunk)


_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[-_]?key|token|password|secret)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)\b(authorization\s*:\s*)(?:bearer\s+)?[^\s]+"
)


def _redact_stderr(
    spec: CommandProviderSpec,
    raw: bytes,
    truncated: bool,
) -> tuple[str | None, bool]:
    if not raw:
        return None, truncated
    output = raw.decode("utf-8", errors="replace")
    for key in spec.env_allowlist:
        value = os.environ.get(key)
        if value:
            output = output.replace(value, "[REDACTED]")
    output = _BEARER_RE.sub("Bearer [REDACTED]", output)
    output = _AUTHORIZATION_RE.sub(
        lambda match: match.group(1) + "[REDACTED]",
        output,
    )
    output = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: match.group(1) + match.group(2) + "[REDACTED]",
        output,
    )
    encoded = output.encode("utf-8")
    if len(encoded) > spec.max_stderr_bytes:
        output = encoded[-spec.max_stderr_bytes :].decode(
            "utf-8",
            errors="ignore",
        )
        truncated = True
    return output or None, truncated


def _attach_stderr(
    result: ProviderResult,
    spec: CommandProviderSpec,
    raw: bytes,
    truncated: bool,
) -> ProviderResult:
    tail, was_truncated = _redact_stderr(spec, raw, truncated)
    return replace(
        result,
        stderr_tail=tail,
        stderr_truncated=was_truncated,
    )


def _provider_trust_result(
    spec: CommandProviderSpec,
    started: float,
    exc: ProviderTrustError,
) -> ProviderResult:
    return ProviderResult(
        provider=spec.name,
        latency_ms=(time.perf_counter() - started) * 1000,
        error=str(exc),
        error_kind="provider_trust",
    )


def run_command_provider(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
    *,
    source: str,
    metadata_defaults: Mapping[str, Any] | None = None,
) -> ProviderResult:
    """Run a provider with launch trust, bounded output and explicit env policy."""

    started = time.perf_counter()
    output = bytearray()
    exceeded = threading.Event()
    stderr_output = bytearray()
    stderr_truncated = threading.Event()
    timed_out = False

    try:
        with _provider_launch_cwd(spec, request) as cwd:
            try:
                command = _verified_command(spec, request.root)
            except ProviderTrustError as exc:
                return _provider_trust_result(spec, started, exc)
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=cwd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=build_provider_env(spec.env_allowlist),
                    **_provider_process_group_kwargs(),
                )
            except (OSError, ValueError) as exc:
                return ProviderResult(
                    provider=spec.name,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=f"provider could not be started: {type(exc).__name__}",
                    error_kind="launch",
                )

            stdout_reader = threading.Thread(
                target=_bounded_reader,
                args=(proc, spec.max_output_bytes, output, exceeded),
                daemon=True,
            )
            assert proc.stderr is not None
            stderr_reader = threading.Thread(
                target=_bounded_tail_reader,
                args=(
                    proc.stderr,
                    spec.max_stderr_bytes,
                    stderr_output,
                    stderr_truncated,
                ),
                daemon=True,
            )
            stdout_reader.start()
            stderr_reader.start()
            try:
                assert proc.stdin is not None
                try:
                    proc.stdin.write(_request_payload(request))
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

                effective_timeout = min(
                    float(spec.timeout_seconds),
                    float(request.timeout_seconds),
                )
                try:
                    returncode = proc.wait(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _terminate_provider_tree(proc)
                    returncode = proc.wait()
            finally:
                for reader in (stdout_reader, stderr_reader):
                    reader.join(timeout=1.0)
                if stdout_reader.is_alive() or stderr_reader.is_alive():
                    _terminate_provider_tree(proc)
                    for reader in (stdout_reader, stderr_reader):
                        reader.join(timeout=1.0)
                if proc.stdin is not None and not proc.stdin.closed:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass
    except OSError as exc:
        return ProviderResult(
            provider=spec.name,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=f"provider cwd could not be created: {type(exc).__name__}",
            error_kind="launch",
        )

    latency_ms = (time.perf_counter() - started) * 1000
    if exceeded.is_set():
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider output exceeded {spec.max_output_bytes} bytes",
            error_kind="output_limit",
            output_limited=True,
            returncode=returncode,
        )
    elif timed_out:
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider timed out after {effective_timeout:g} seconds",
            error_kind="timeout",
            timed_out=True,
            returncode=returncode,
        )
    elif returncode != 0:
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider exited with status {returncode}",
            error_kind="exit",
            returncode=returncode,
        )
    else:
        result = _result_from_bytes(
            spec,
            request,
            source,
            metadata_defaults,
            bytes(output),
            latency_ms,
            returncode,
        )
    return _attach_stderr(
        result,
        spec,
        bytes(stderr_output),
        stderr_truncated.is_set(),
    )


async def run_command_provider_async(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
    *,
    source: str,
    metadata_defaults: Mapping[str, Any] | None = None,
) -> ProviderResult:
    """Run a command provider with the same launch trust policy as sync."""

    started = time.perf_counter()
    try:
        with _provider_launch_cwd(spec, request) as cwd:
            try:
                command = _verified_command(spec, request.root)
            except ProviderTrustError as exc:
                return _provider_trust_result(spec, started, exc)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=cwd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=build_provider_env(spec.env_allowlist),
                    **_provider_process_group_kwargs(),
                )
            except (OSError, ValueError) as exc:
                return ProviderResult(
                    provider=spec.name,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=f"provider could not be started: {type(exc).__name__}",
                    error_kind="launch",
                )

            effective_timeout = min(
                float(spec.timeout_seconds),
                float(request.timeout_seconds),
            )

            async def exchange() -> tuple[bytes, bool, int, bytes, bool]:
                assert proc.stdout is not None
                assert proc.stderr is not None
                stdout_task = asyncio.create_task(
                    _bounded_async_reader(
                        proc.stdout,
                        spec.max_output_bytes,
                    )
                )
                stderr_task = asyncio.create_task(
                    _bounded_async_tail_reader(
                        proc.stderr,
                        spec.max_stderr_bytes,
                    )
                )
                try:
                    if proc.stdin is not None:
                        try:
                            proc.stdin.write(_request_payload(request))
                            await proc.stdin.drain()
                        except (
                            BrokenPipeError,
                            ConnectionResetError,
                            OSError,
                        ):
                            pass
                        finally:
                            proc.stdin.close()

                    output_bytes, output_exceeded = await stdout_task
                    if output_exceeded and proc.returncode is None:
                        _terminate_provider_tree(proc)
                    stderr_bytes, stderr_was_truncated = await stderr_task
                    returncode = await proc.wait()
                    return (
                        output_bytes,
                        output_exceeded,
                        returncode,
                        stderr_bytes,
                        stderr_was_truncated,
                    )
                finally:
                    for task in (stdout_task, stderr_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(
                        stdout_task,
                        stderr_task,
                        return_exceptions=True,
                    )

            exchange_task = asyncio.create_task(exchange())
            timed_out = False
            try:
                (
                    output,
                    exceeded,
                    returncode,
                    stderr_output,
                    stderr_truncated,
                ) = await asyncio.wait_for(
                    asyncio.shield(exchange_task),
                    timeout=effective_timeout,
                )
            except TimeoutError:
                timed_out = True
                if proc.returncode is None:
                    _terminate_provider_tree(proc)
                await proc.wait()
                try:
                    (
                        output,
                        exceeded,
                        returncode,
                        stderr_output,
                        stderr_truncated,
                    ) = await exchange_task
                except (OSError, RuntimeError):
                    output = b""
                    exceeded = False
                    returncode = (
                        int(proc.returncode)
                        if proc.returncode is not None
                        else -1
                    )
                    stderr_output = b""
                    stderr_truncated = False
            except asyncio.CancelledError:
                if proc.returncode is None:
                    _terminate_provider_tree(proc)
                await proc.wait()
                if not exchange_task.done():
                    exchange_task.cancel()
                await asyncio.gather(
                    exchange_task,
                    return_exceptions=True,
                )
                raise
    except OSError as exc:
        return ProviderResult(
            provider=spec.name,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=f"provider cwd could not be created: {type(exc).__name__}",
            error_kind="launch",
        )

    latency_ms = (time.perf_counter() - started) * 1000
    if exceeded:
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider output exceeded {spec.max_output_bytes} bytes",
            error_kind="output_limit",
            output_limited=True,
            returncode=returncode,
        )
    elif timed_out:
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider timed out after {effective_timeout:g} seconds",
            error_kind="timeout",
            timed_out=True,
            returncode=returncode,
        )
    elif returncode != 0:
        result = ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider exited with status {returncode}",
            error_kind="exit",
            returncode=returncode,
        )
    else:
        result = _result_from_bytes(
            spec,
            request,
            source,
            metadata_defaults,
            output,
            latency_ms,
            returncode,
        )
    return _attach_stderr(
        result,
        spec,
        stderr_output,
        stderr_truncated,
    )
