from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from .models import ContextItem


VALID_INTENTS = {"exact", "semantic", "structural", "mixed", "all"}


def configured_retrievers(config: dict, intent: str) -> list[dict]:
    raw = ((config.get("context") or {}).get("external_retrievers") or [])
    out = []
    for item in raw:
        if not isinstance(item, dict) or item.get("enabled", True) is False:
            continue
        name = str(item.get("name", "")).strip()
        command = str(item.get("command", "")).strip()
        intents = {str(x).strip().lower() for x in (item.get("intents") or ["all"])}
        if not name or not command or not intents.issubset(VALID_INTENTS):
            continue
        if "all" in intents or intent in intents:
            out.append(item)
    return out


def run_retriever(root: Path, query: str, intent: str, spec: dict, limit: int) -> list[ContextItem]:
    name = str(spec.get("name", "external")).strip()
    command = str(spec.get("command", "")).strip()
    timeout = max(1, int(spec.get("timeout_seconds", 8)))
    request = json.dumps({"query": query, "root": str(root), "limit": int(limit), "intent": intent}) + "\n"
    try:
        proc = subprocess.run(
            shlex.split(command), cwd=root, input=request, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = []
        for line in proc.stdout.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                payload.append(record)
    if isinstance(payload, dict):
        payload = payload.get("items", [])
    if not isinstance(payload, list):
        return []
    items = []
    for record in payload[: max(1, limit)]:
        if not isinstance(record, dict):
            continue
        text = str(record.get("text", "")).strip()
        if not text:
            continue
        try:
            score = float(record.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        metadata = dict(record.get("metadata") or {})
        for key in ("path", "file", "line", "start_line", "end_line", "sha256"):
            if key in record and key not in metadata:
                metadata[key] = record[key]
        metadata.update({"retriever": name, "plugin": True})
        items.append(ContextItem(f"external:{name}", text, score, False, metadata))
    items.sort(key=lambda item: -item.score)
    return items
