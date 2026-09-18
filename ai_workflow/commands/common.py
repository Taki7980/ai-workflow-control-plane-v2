from __future__ import annotations

import json
import os
from pathlib import Path
from ..config import find_project_root

def _root(args) -> Path:
    return Path(args.root).resolve() if getattr(args, "root", None) else find_project_root()

def _json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

def _load_json_object(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input report must be a JSON object")
    return data

def _signing_key_from_env(name: str) -> bytes:
    value = os.getenv(name, "")
    if not value:
        raise ValueError(
            f"policy signing key environment variable is empty: {name}"
        )
    return value.encode()
