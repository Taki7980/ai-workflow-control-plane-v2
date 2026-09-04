from __future__ import annotations
import json, shutil, subprocess, sys
from pathlib import Path
from .providers import detect
from .indexer import load_state, sha256
from .handoff import validate as validate_handoff

def run(root: Path, config: dict) -> tuple[dict, bool]:
    status = detect(root, config)
    state = load_state(root)
    stale = 0
    for rel, meta in state.get("files", {}).items():
        p = root / rel
        try:
            if not p.exists() or sha256(p) != meta.get("sha256"):
                stale += 1
        except OSError:
            stale += 1
    handoff_path = root / ".ai" / "HANDOFF.md"
    handoff_present = handoff_path.exists()
    handoff_errors = validate_handoff(root, int(config["handoff"].get("max_lines", 30))) if handoff_present else []
    tracked = len(state.get("files", {}))
    recommendations = []
    if not state:
        recommendations.append("Local index not built; run `ai-workflow index`")
    crg_installed = shutil.which("code-review-graph") is not None
    crg_health = {"installed": crg_installed, "ready": status.code_review_graph}
    if crg_installed:
        try:
            proc = subprocess.run(["code-review-graph", "status", "--repo", str(root), "--json"], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                crg_health["ready"] = True
                try:
                    crg_health["status"] = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    crg_health["status"] = proc.stdout.strip()[:1000]
            else:
                crg_health["ready"] = False
                crg_health["error"] = (proc.stderr or proc.stdout).strip()[:500]
        except (OSError, subprocess.TimeoutExpired) as exc:
            crg_health["ready"] = False
            crg_health["error"] = str(exc)
    min_crg = int(config.get("context", {}).get("crg", {}).get("min_source_files", 250))
    if tracked >= min_crg and not crg_installed:
        recommendations.append(f"repository index has {tracked} source files; consider Code Review Graph for structural Full-lane work")
    elif crg_installed and not crg_health["ready"]:
        recommendations.append("Code Review Graph is installed but no healthy graph was detected; run `code-review-graph build`")
    if not status.superpowers:
        recommendations.append("Superpowers not detected; Full lane will use native Plan -> Build -> Review")
    result = {
        "python": sys.version.split()[0],
        "providers": status.to_dict(),
        "code_review_graph_health": crg_health,
        "config_version": config.get("version"),
        "index": {"present": bool(state), "tracked_files": tracked, "stale_files": stale},
        "handoff_errors": handoff_errors,
        "recommendations": recommendations,
    }
    ok = config.get("version") == 2 and bool(state) and not handoff_errors and stale == 0
    return result, ok
