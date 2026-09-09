from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .path_policy import PathOutsideWorkspace, resolve_within_root


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_head(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=3, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else None


def _stable_index_identity(root: Path) -> dict[str, Any] | None:
    index_path = root / 'ai-workspace' / 'generated' / 'index-state.json'
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    files = data.get('files')
    if not isinstance(files, dict):
        return None
    return {
        'version': data.get('version'),
        'files': files,
    }


def _stable_json_digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return _sha256_bytes(encoded)


def workspace_fingerprint(root: Path, changed_files: list[str] | None = None) -> dict:
    root = root.resolve()
    changed = []
    for rel in sorted(set(changed_files or [])):
        try:
            path = resolve_within_root(root, rel)
        except (PathOutsideWorkspace, OSError):
            changed.append({'path': rel, 'state': 'rejected', 'sha256': None})
            continue
        if not path.exists() or not path.is_file():
            changed.append({'path': rel, 'state': 'missing', 'sha256': None})
            continue
        try:
            digest = _sha256_bytes(path.read_bytes())
        except OSError:
            changed.append({'path': rel, 'state': 'unreadable', 'sha256': None})
            continue
        changed.append({'path': rel, 'state': 'present', 'sha256': digest})

    index_identity = _stable_index_identity(root)
    index_digest = _stable_json_digest(index_identity) if index_identity is not None else None

    identity_payload = {
        'schema': 2,
        'git_head': _git_head(root),
        'index_state_sha256': index_digest,
        'changed_files': changed,
    }
    return {
        'root': str(root),
        **identity_payload,
        'fingerprint': _stable_json_digest(identity_payload),
    }
