from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from .provider_runner import CommandProviderSpec, command_provider_spec


REGISTRY_ENV = "AI_WORKFLOW_PROVIDER_REGISTRY"
UNSAFE_REPO_COMMANDS_ENV = "AI_WORKFLOW_ALLOW_REPO_PROVIDER_COMMANDS"


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def unsafe_repo_commands_enabled() -> bool:
    """Return whether explicitly unsafe repository-defined commands are enabled."""

    return _truthy_env(UNSAFE_REPO_COMMANDS_ENV)


def default_registry_path() -> Path:
    """Return the user-owned trusted provider registry location."""

    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if base:
            return Path(base) / "ai-workflow" / "providers.json"
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ai-workflow" / "providers.json"
    return Path.home() / ".config" / "ai-workflow" / "providers.json"


def trusted_registry_path() -> Path:
    configured = os.getenv(REGISTRY_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{REGISTRY_ENV} must be an absolute path")
        return path.resolve()
    return default_registry_path().expanduser().resolve()


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


def _load_registry(root: Path) -> Mapping[str, Any]:
    path = trusted_registry_path()
    if _is_within(root, path):
        raise ValueError("trusted provider registry must live outside the repository")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"trusted provider registry not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("trusted provider registry could not be read") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        raise ValueError("trusted provider registry must contain a providers object")
    return payload["providers"]


def _validated_executable(root: Path, raw: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    command = raw.get("command")
    if not isinstance(command, (list, tuple)) or not command:
        raise ValueError("trusted provider command must be a non-empty argv array")

    argv = tuple(str(part) for part in command)
    executable = Path(argv[0]).expanduser()
    if not executable.is_absolute():
        raise ValueError("trusted provider executable must be an absolute path")
    try:
        executable = executable.resolve(strict=True)
    except OSError as exc:
        raise ValueError("trusted provider executable does not exist") from exc
    if not executable.is_file():
        raise ValueError("trusted provider executable is not a regular file")
    if _is_within(root, executable):
        raise ValueError("trusted provider executable must live outside the repository")

    expected = str(raw.get("sha256") or "").strip().lower()
    if expected.startswith("sha256:"):
        expected = expected.removeprefix("sha256:")
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("trusted provider requires a sha256 digest")
    actual = _sha256_file(executable)
    if not hmac.compare_digest(actual, expected):
        raise ValueError("trusted provider executable digest mismatch")

    # A digest-pinned interpreter must not be allowed to execute a script supplied
    # by the repository. Relative path arguments resolve against the repository
    # because provider processes run with cwd=root.
    for arg in argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        candidate = Path(arg).expanduser()
        if candidate.is_absolute():
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
        else:
            try:
                resolved = (root / candidate).resolve(strict=True)
            except OSError:
                continue
        if _is_within(root, resolved):
            raise ValueError(
                "trusted provider command may not execute repository-owned path arguments"
            )

    return str(executable), (str(executable), *argv[1:])


def _positive_cap(value: Any, fallback: int | float) -> int | float:
    try:
        parsed = type(fallback)(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if parsed > 0 else fallback


def resolve_trusted_provider(
    root: Path,
    provider_id: str,
    project_spec: Mapping[str, Any],
    *,
    default_name: str = "provider",
) -> CommandProviderSpec:
    """Resolve executable authority from a user/admin-owned registry.

    Repository configuration may select a provider ID and tighten resource
    limits, but it cannot supply executable paths, environment variables,
    digests, or execution semantics.
    """

    provider_id = provider_id.strip()
    if not provider_id:
        raise ValueError("provider_id must not be blank")

    providers = _load_registry(root)
    trusted = providers.get(provider_id)
    if not isinstance(trusted, dict):
        raise ValueError(f"trusted provider is not registered: {provider_id}")

    _executable, argv = _validated_executable(root, trusted)
    trusted_raw = dict(trusted)
    trusted_raw["name"] = str(trusted.get("name") or provider_id)
    trusted_raw["command"] = list(argv)
    trusted_spec = command_provider_spec(trusted_raw, default_name=provider_id)

    requested_timeout = float(
        _positive_cap(project_spec.get("timeout_seconds"), trusted_spec.timeout_seconds)
    )
    requested_output = int(
        _positive_cap(project_spec.get("max_output_bytes"), trusted_spec.max_output_bytes)
    )
    intents = project_spec.get("intents", trusted_spec.intents)
    if isinstance(intents, str):
        project_intents = (intents,)
    elif isinstance(intents, (list, tuple)) and all(
        isinstance(item, str) and item.strip() for item in intents
    ):
        project_intents = tuple(str(item) for item in intents)
    else:
        raise ValueError("provider intents must be a list of non-empty strings")

    return replace(
        trusted_spec,
        name=str(project_spec.get("name") or default_name),
        command=argv,
        timeout_seconds=min(trusted_spec.timeout_seconds, requested_timeout),
        max_output_bytes=min(trusted_spec.max_output_bytes, requested_output),
        intents=project_intents,
        executable_trust="trusted_registry_digest",
    )


def resolve_project_provider(
    root: Path,
    raw: Mapping[str, Any],
    *,
    default_name: str = "provider",
) -> CommandProviderSpec:
    """Resolve a project provider without granting repository executable authority."""

    provider_id = str(raw.get("provider_id") or "").strip()
    if provider_id:
        forbidden = []
        if raw.get("command") not in (None, "", []):
            forbidden.append("command")
        if raw.get("env_allowlist") not in (None, [], ()):
            forbidden.append("env_allowlist")
        if raw.get("sha256") not in (None, ""):
            forbidden.append("sha256")
        if raw.get("semantics") not in (None, {}):
            forbidden.append("semantics")
        if forbidden:
            raise ValueError(
                "repository provider_id configuration may not set trusted fields: "
                + ", ".join(forbidden)
            )
        return resolve_trusted_provider(
            root,
            provider_id,
            raw,
            default_name=default_name,
        )

    if unsafe_repo_commands_enabled():
        return command_provider_spec(raw, default_name=default_name)

    raise ValueError(
        "repository-defined provider commands are disabled; configure provider_id "
        "in the project and register executable authority outside the repository"
    )
