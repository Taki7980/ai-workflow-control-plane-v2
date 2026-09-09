from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .indexer import sha256
from .math_retrieval import BM25Scorer, tokenize
from .memory_store import SQLiteMemoryStore
from .path_policy import PathOutsideWorkspace, resolve_within_root

MEMORY_TYPES = {"decision", "incident", "verified-fix", "architecture", "pattern", "optimization", "constraint"}


def _store(root: Path) -> SQLiteMemoryStore:
    return SQLiteMemoryStore(root)


def _memory_file(root: Path, raw: str) -> tuple[str, Path]:
    try:
        resolved = resolve_within_root(root, raw)
    except (PathOutsideWorkspace, OSError) as exc:
        raise ValueError(f"memory file path must stay within workspace: {raw}") from exc
    rel = resolved.relative_to(root.resolve()).as_posix()
    return rel, resolved


def add_memory(root: Path, type_: str, keywords: str, summary: str, evidence: str = "", files: list[str] | None = None, confidence: float = 0.8) -> dict:
    if type_ not in MEMORY_TYPES:
        raise ValueError(f"unsupported memory type: {type_}")
    now = datetime.now(timezone.utc).isoformat()
    related = []
    source_hashes = {}
    for raw in files or []:
        rel, p = _memory_file(root, raw)
        related.append(rel)
        if p.exists() and p.is_file():
            source_hashes[rel] = sha256(p)
    record = {
        "id": f"mem-{uuid.uuid4().hex[:12]}", "type": type_, "created_at": now, "verified_at": now,
        "keywords": list(dict.fromkeys(tokenize(keywords))),
        "summary": summary.strip(), "evidence": evidence.strip(), "files": related,
        "source_hashes": source_hashes, "confidence": max(0.0, min(1.0, float(confidence)))
    }
    _store(root).insert(record)
    return record


def _stale(root: Path, record: dict) -> bool:
    source_hashes = record.get("source_hashes", {})
    if any(rel not in source_hashes for rel in record.get("files", [])):
        return True
    for rel, expected in source_hashes.items():
        try:
            p = resolve_within_root(root, rel)
        except (PathOutsideWorkspace, OSError):
            return True
        if not p.exists():
            return True
        try:
            if sha256(p) != expected:
                return True
        except OSError:
            return True
    return False


def search_memory(root: Path, query: str, limit: int = 5, minimum_confidence: float = 0.0, exclude_stale: bool = False) -> list[dict]:
    records: list[dict] = []
    texts: list[str] = []
    for record in _store(root).list_records():
        if float(record.get("confidence", 0)) < minimum_confidence:
            continue
        stale = _stale(root, record)
        if exclude_stale and stale:
            continue
        text = " ".join(record.get("keywords", [])) + " " + record.get("summary", "") + " " + record.get("evidence", "")
        records.append({**record, "stale": stale})
        texts.append(text)

    scorer = BM25Scorer()
    scorer.fit(texts, records)
    rows = []
    for score, record in scorer.rank(query):
        out = dict(record)
        out["score"] = score * float(out.get("confidence", 0))
        rows.append(out)
    rows.sort(key=lambda item: (item["stale"], -item["score"], -float(item.get("confidence", 0))))
    return rows[:limit]


def list_memories(root: Path) -> list[dict]:
    rows = []
    for record in _store(root).list_records():
        row = dict(record)
        row["stale"] = _stale(root, row)
        rows.append(row)
    rows.sort(key=lambda x: (x.get("stale", False), -float(x.get("confidence", 0))))
    return rows


def prune_stale(root: Path) -> dict:
    store = _store(root)
    records = store.list_records()
    kept = [record for record in records if not _stale(root, record)]
    pruned = len(records) - len(kept)
    store.replace_all(kept)
    return {"kept": len(kept), "pruned": pruned}


def export_memory_jsonl(root: Path, destination: Path) -> int:
    return _store(root).export_jsonl(destination)
