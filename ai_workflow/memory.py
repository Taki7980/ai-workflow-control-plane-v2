from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from .indexer import sha256
from .math_retrieval import BM25Scorer, tokenize

MEMORY_TYPES = {"decision", "incident", "verified-fix", "architecture", "pattern", "optimization", "constraint"}

def _path(root: Path) -> Path:
    p = root / "ai-workspace" / "memory" / "memory.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text("", encoding="utf-8")
    return p

def add_memory(root: Path, type_: str, keywords: str, summary: str, evidence: str = "", files: list[str] | None = None, confidence: float = 0.8) -> dict:
    if type_ not in MEMORY_TYPES:
        raise ValueError(f"unsupported memory type: {type_}")
    now = datetime.now(timezone.utc).isoformat()
    related = []
    source_hashes = {}
    for raw in files or []:
        rel = Path(raw).as_posix()
        p = root / rel
        related.append(rel)
        if p.exists() and p.is_file():
            source_hashes[rel] = sha256(p)
    record = {
        "id": f"mem-{uuid.uuid4().hex[:12]}", "type": type_, "created_at": now, "verified_at": now,
        "keywords": list(dict.fromkeys(tokenize(keywords))),
        "summary": summary.strip(), "evidence": evidence.strip(), "files": related,
        "source_hashes": source_hashes, "confidence": max(0.0, min(1.0, float(confidence)))
    }
    p = _path(root)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

def _stale(root: Path, record: dict) -> bool:
    source_hashes = record.get("source_hashes", {})
    if any(rel not in source_hashes for rel in record.get("files", [])):
        return True
    for rel, expected in source_hashes.items():
        p = root / rel
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
    try:
        lines = _path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
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
    try:
        for line in _path(root).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["stale"] = _stale(root, r)
                rows.append(r)
    except (OSError, json.JSONDecodeError):
        pass
    rows.sort(key=lambda x: (x.get("stale", False), -float(x.get("confidence", 0))))
    return rows


def prune_stale(root: Path) -> dict:
    p = _path(root)
    if not p.exists():
        return {"kept": 0, "pruned": 0}
    kept, pruned = [], 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if _stale(root, r):
                pruned += 1
            else:
                kept.append(r)
        except json.JSONDecodeError:
            pass
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    return {"kept": len(kept), "pruned": pruned}
