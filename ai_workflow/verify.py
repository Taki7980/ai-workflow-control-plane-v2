from __future__ import annotations
import os, shlex, subprocess
from pathlib import Path
from .compress import compress_text
from .handoff import validate as validate_handoff


def _split_command(raw: str) -> list[str]:
    if os.name == "nt":
        tokens = shlex.split(raw, posix=False)
        cleaned = []
        for t in tokens:
            if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
                if len(t) >= 2:
                    t = t[1:-1]
            cleaned.append(t)
        return cleaned
    return shlex.split(raw, posix=True)


def run_checks(root: Path, checks: list[str], max_lines: int = 60) -> dict:
    results = []
    for raw in checks:
        try:
            argv = _split_command(raw)
        except ValueError as exc:
            results.append({"check": raw, "returncode": 2, "output": f"parse error: {exc}"})
            continue
        if not argv:
            continue
        try:
            proc = subprocess.run(argv, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False)
            output = compress_text(proc.stdout or "", max_lines=max_lines, max_chars=10000)
            results.append({"check": raw, "returncode": proc.returncode, "output": output})
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({"check": raw, "returncode": 124, "output": str(exc)})
    return {"ok": bool(checks) and all(r["returncode"] == 0 for r in results), "checks": results}


def verify(root: Path, checks: list[str], handoff_max_lines: int) -> dict:
    handoff_errors = validate_handoff(root, handoff_max_lines)
    result = run_checks(root, checks) if checks else {"ok": False, "checks": []}
    result["handoff_errors"] = handoff_errors
    result["ok"] = result["ok"] and not handoff_errors
    return result
