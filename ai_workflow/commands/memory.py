from __future__ import annotations

from pathlib import Path
from ..config import load_config
from ..memory import add_memory, export_memory_jsonl, list_memories, prune_stale, search_memory

from .common import _json, _root

def cmd_memory_add(args):
    _json(
        add_memory(
            _root(args),
            args.type,
            args.keywords,
            args.summary,
            args.evidence or "",
            args.file or [],
            args.confidence,
        )
    )

def cmd_memory_search(args):
    root = _root(args)
    cfg = load_config(root)
    _json(
        search_memory(
            root,
            args.query,
            args.limit or int(cfg["memory"]["max_results"]),
            float(cfg["memory"].get("minimum_confidence", 0.55)),
        )
    )

def cmd_memory_list(args):
    _json(list_memories(_root(args)))

def cmd_memory_prune(args):
    _json(prune_stale(_root(args)))

def cmd_memory_export(args):
    destination = Path(args.output).resolve()
    count = export_memory_jsonl(_root(args), destination)
    _json({"format": "jsonl", "output": str(destination), "records": count})
