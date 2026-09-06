from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


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


def workspace_fingerprint(root: Path, changed_files: list[str] | None = None) -> dict:
    root = root.resolve()
    changed = []
    for rel in sorted(set(changed_files or [])):
        path = root / rel
        if not path.exists() or not path.is_file():
            changed.append({'path': rel, 'state': 'missing', 'sha256': None})
            continue
        try:
            digest = _sha256_bytes(path.read_bytes())
        except OSError:
            changed.append({'path': rel, 'state': 'unreadable', 'sha256': None})
            continue
        changed.append({'path': rel, 'state': 'present', 'sha256': digest})

    index_path = root / 'ai-workspace' / 'generated' / 'index-state.json'
    try:
        index_digest = _sha256_bytes(index_path.read_bytes()) if index_path.exists() else None
    except OSError:
        index_digest = None

    payload = {
        'root': str(root),
        'git_head': _git_head(root),
        'index_state_sha256': index_digest,
        'changed_files': changed,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return {**payload, 'fingerprint': _sha256_bytes(encoded)}
