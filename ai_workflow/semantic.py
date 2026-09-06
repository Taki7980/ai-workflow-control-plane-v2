from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from .models import ContextItem


def configured_command(config: dict) -> str:
    semantic = ((config.get("context") or {}).get("semantic") or {})
    if str(semantic.get("mode", "auto")).lower() == "off":
        return ""
    return os.getenv("AI_WORKFLOW_SEMANTIC_CMD", "").strip() or str(semantic.get("command", "")).strip()


def semantic_ready(config: dict) -> bool:
    return bool(configured_command(config))


def semantic_context(root: Path, query: str, config: dict, limit: int) -> list[ContextItem]:
    command = configured_command(config)
    if not command:
        return []

    semantic = ((config.get("context") or {}).get("semantic") or {})
    timeout = max(1, int(semantic.get("timeout_seconds", 8)))
    request = json.dumps({"query": query, "root": str(root), "limit": int(limit)}) + "\n"
    try:
        proc = subprocess.run(
            shlex.split(command),
            cwd=root,
            input=request,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    raw = proc.stdout.strip()
    records: list[dict] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = parsed.get("items", [])
        if isinstance(parsed, list):
            records = [x for x in parsed if isinstance(x, dict)]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)

    out: list[ContextItem] = []
    for record in records[: max(1, int(limit))]:
        text = str(record.get("text", "")).strip()
        if not text:
            continue
        try:
            score = float(record.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        metadata = dict(record.get("metadata") or {})
        for key in ("path", "line", "start_line", "end_line", "sha256"):
            if key in record and key not in metadata:
                metadata[key] = record[key]
        metadata.update({"retriever": "semantic", "trust": metadata.get("trust", "untrusted_repository_content")})
        out.append(ContextItem("semantic", text, score, False, metadata))
    out.sort(key=lambda item: -item.score)
    return out
