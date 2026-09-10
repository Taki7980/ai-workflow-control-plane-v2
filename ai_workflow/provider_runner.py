from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .execution_semantics import ProviderSemantics
from .models import ContextItem
from .path_policy import confine_metadata_paths
from .retrieval_contracts import ProviderResult, RetrievalRequest


DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
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
    intents: tuple[str, ...] = ("all",)
    env_allowlist: tuple[str, ...] = ()
    executable_trust: str = "configured_local_executable"
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

    return CommandProviderSpec(
        name=str(raw.get("name") or default_name),
        command=argv,
        timeout_seconds=float(raw.get("timeout_seconds", 8)),
        max_output_bytes=int(
            raw.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES)
        ),
        intents=tuple(intents),
        env_allowlist=tuple(env_allowlist),
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
                try:
                    proc.kill()
                except OSError:
                    pass
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
                raise ValueError("provider JSONL rows must be objects")
            rows.append(row)
        if not rows and raw.strip():
            raise ValueError("provider returned invalid JSON/JSONL payload")
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
        metadata["provider_trust"] = "configured_local_executable"
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
            metadata_defaults,
        ),
        latency_ms=latency_ms,
        returncode=returncode,
    )


def run_command_provider(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
    *,
    source: str,
    metadata_defaults: Mapping[str, Any] | None = None,
) -> ProviderResult:
    """Run a provider with bounded output, timeout and explicit env policy."""

    started = time.perf_counter()
    output = bytearray()
    exceeded = threading.Event()
    timed_out = False

    try:
        proc = subprocess.Popen(
            spec.command,
            cwd=request.root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=build_provider_env(spec.env_allowlist),
        )
    except (OSError, ValueError) as exc:
        return ProviderResult(
            provider=spec.name,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=f"provider could not be started: {type(exc).__name__}",
            error_kind="launch",
        )

    reader = threading.Thread(
        target=_bounded_reader,
        args=(proc, spec.max_output_bytes, output, exceeded),
        daemon=True,
    )
    reader.start()
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
            proc.kill()
            returncode = proc.wait()
    finally:
        reader.join(timeout=1.0)
        if reader.is_alive():
            try:
                proc.kill()
            except OSError:
                pass
            reader.join(timeout=1.0)
        if proc.stdin is not None and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass

    latency_ms = (time.perf_counter() - started) * 1000
    if exceeded.is_set():
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider output exceeded {spec.max_output_bytes} bytes",
            error_kind="output_limit",
            output_limited=True,
            returncode=returncode,
        )
    if timed_out:
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider timed out after {effective_timeout:g} seconds",
            error_kind="timeout",
            timed_out=True,
            returncode=returncode,
        )
    if returncode != 0:
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider exited with status {returncode}",
            error_kind="exit",
            returncode=returncode,
        )
    return _result_from_bytes(
        spec,
        request,
        source,
        metadata_defaults,
        bytes(output),
        latency_ms,
        returncode,
    )


async def run_command_provider_async(
    spec: CommandProviderSpec,
    request: RetrievalRequest,
    *,
    source: str,
    metadata_defaults: Mapping[str, Any] | None = None,
) -> ProviderResult:
    """Run a command provider with native asyncio subprocess handling."""

    started = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *spec.command,
            cwd=request.root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=build_provider_env(spec.env_allowlist),
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

    async def exchange() -> tuple[bytes, bool, int]:
        if proc.stdin is not None:
            try:
                proc.stdin.write(_request_payload(request))
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                proc.stdin.close()
        assert proc.stdout is not None
        output, exceeded = await _bounded_async_reader(
            proc.stdout,
            spec.max_output_bytes,
        )
        if exceeded and proc.returncode is None:
            proc.kill()
        returncode = await proc.wait()
        return output, exceeded, returncode

    try:
        output, exceeded, returncode = await asyncio.wait_for(
            exchange(),
            timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        return ProviderResult(
            provider=spec.name,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=f"provider timed out after {effective_timeout:g} seconds",
            error_kind="timeout",
            timed_out=True,
            returncode=proc.returncode,
        )
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise

    latency_ms = (time.perf_counter() - started) * 1000
    if exceeded:
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider output exceeded {spec.max_output_bytes} bytes",
            error_kind="output_limit",
            output_limited=True,
            returncode=returncode,
        )
    if returncode != 0:
        return ProviderResult(
            provider=spec.name,
            latency_ms=latency_ms,
            error=f"provider exited with status {returncode}",
            error_kind="exit",
            returncode=returncode,
        )
    return _result_from_bytes(
        spec,
        request,
        source,
        metadata_defaults,
        output,
        latency_ms,
        returncode,
    )
