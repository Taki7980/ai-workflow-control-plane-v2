from __future__ import annotations
import shutil, subprocess

def compress_with_rtk(text: str, filter_name: str | None = None) -> str | None:
    if not shutil.which("rtk"):
        return None
    try:
        cmd = ["rtk", "pipe"]
        if filter_name:
            cmd.extend(["--filter", filter_name])
        p = subprocess.run(
            cmd,
            input=text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def compress_text(text: str, max_lines: int = 80, max_chars: int = 12000, prefer_rtk: bool = False, filter_name: str | None = None) -> str:
    if prefer_rtk:
        rtk_out = compress_with_rtk(text, filter_name)
        if rtk_out is not None:
            return rtk_out

    lines = text.splitlines()
    if len(lines) > max_lines:
        head = max(1, int(max_lines * 0.75))
        tail = max_lines - head
        lines = lines[:head] + [f"... [{len(lines) - max_lines} LINES OMITTED] ..."] + lines[-tail:]
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[: max_chars - 40].rstrip() + "\n... [CHARACTER CAP REACHED]"
    return out + ("\n" if out and not out.endswith("\n") else "")
