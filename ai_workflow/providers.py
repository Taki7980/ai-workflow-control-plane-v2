from __future__ import annotations
import os, shutil
from pathlib import Path
from dataclasses import dataclass, asdict
from .models import Lane, Risk, RouteDecision
from .semantic import semantic_ready

@dataclass
class ProviderStatus:
    superpowers: bool
    code_review_graph: bool
    semantic: bool
    rtk: bool
    ripgrep: bool

    def to_dict(self):
        return asdict(self)

def _bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    return value.strip().lower() in {"1","true","yes","on"}

def _has_superpowers(root: Path) -> bool:
    forced = _bool_env("AI_WORKFLOW_SUPERPOWERS")
    if forced is not None:
        return forced
    candidates = [
        root / ".agents" / "skills" / "superpowers",
        Path.home() / ".agents" / "skills" / "superpowers",
        Path.home() / ".codex" / "superpowers",
        Path.home() / ".codex" / "skills" / "superpowers",
        Path.home() / ".gemini" / "skills" / "superpowers",
        Path.home() / ".config" / "opencode" / "skills" / "superpowers",
    ]
    if any(p.exists() for p in candidates):
        return True
    plugin_roots = [Path.home()/'.claude'/'plugins', Path.home()/'.codex'/'plugins', Path.home()/'.gemini'/'extensions']
    for base in plugin_roots:
        if not base.exists():
            continue
        try:
            if next(base.glob('**/*superpowers*'), None) is not None:
                return True
        except OSError:
            pass
    return False

def _has_crg(root: Path) -> bool:
    return shutil.which("code-review-graph") is not None and (root / ".code-review-graph" / "graph.db").is_file()


def detect(root: Path, config: dict | None = None) -> ProviderStatus:
    cfg = config or {}
    sp_mode = (cfg.get('execution', {}).get('superpowers', {}) or {}).get('mode','auto')
    crg_mode = (cfg.get('context', {}).get('crg', {}) or {}).get('mode','auto')
    sp = _has_superpowers(root) if sp_mode == 'auto' else sp_mode == 'on'
    crg = _has_crg(root) if crg_mode == 'auto' else crg_mode == 'on'
    return ProviderStatus(
        superpowers=sp,
        code_review_graph=crg,
        semantic=semantic_ready(cfg),
        rtk=shutil.which('rtk') is not None,
        ripgrep=shutil.which('rg') is not None,
    )

def execution_provider(lane: Lane, config: dict, status: ProviderStatus) -> str:
    if lane == Lane.FULL and config['execution'].get('prefer_superpowers_for_full', True) and status.superpowers:
        return 'superpowers'
    return 'native'

def model_tier(decision: RouteDecision, config: dict) -> str:
    policy = config.get('models', {})
    if decision.lane == Lane.ANSWER:
        return policy.get('answer','fast')
    if decision.lane == Lane.SMALL:
        return policy.get('small','fast')
    if decision.risk == Risk.HIGH:
        return policy.get('full_high','capable')
    return policy.get('full_medium','standard')
