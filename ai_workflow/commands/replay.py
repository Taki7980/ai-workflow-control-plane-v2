from __future__ import annotations

from ..config import load_config
from ..run_journal import replay_run_journal
from .common import _json, _root


def cmd_replay(args) -> None:
    root = _root(args)
    result = replay_run_journal(
        root,
        args.run_id,
        load_config(root),
    )
    _json(result)
    if getattr(args, "strict", False):
        integrity = result.get("integrity") or {}
        compatibility = result.get("compatibility") or {}
        if (
            not result.get("found")
            or not integrity.get("valid")
            or not compatibility.get("compatible")
        ):
            raise SystemExit(1)
