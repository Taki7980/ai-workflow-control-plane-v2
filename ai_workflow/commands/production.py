from __future__ import annotations

from ..config import estimate_tokens, find_project_root, load_config
from ..production_store import (
    mirror_learning_event,
    production_store_status,
    reconcile_learning_store,
    sync_learning_store,
)

from .common import _json, _root

def cmd_production_status(args):
    root = _root(args)
    _json(production_store_status(root, load_config(root)))

def cmd_production_sync(args):
    root = _root(args)
    _json(sync_learning_store(root, load_config(root)))

def cmd_production_reconcile(args):
    root = _root(args)
    result = reconcile_learning_store(root, load_config(root))
    _json(result)
    if not result["consistent"]:
        raise SystemExit(1)
