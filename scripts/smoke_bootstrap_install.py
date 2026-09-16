from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "9.8.7"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, threading.Thread, str]:
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}"


def _prepare_release(directory: Path, installer: str) -> tuple[str, str]:
    if installer == "shell":
        asset = f"ai-workflow-v{VERSION}-linux-x86_64"
        target = directory / asset
        target.write_text(
            "#!/usr/bin/env sh\n"
            "if [ \"$1\" = \"--version\" ]; then\n"
            f"  echo \"{VERSION}\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        target.chmod(0o755)
    else:
        asset = f"ai-workflow-v{VERSION}-windows-x86_64.exe"
        target = directory / asset
        shutil.copy2(sys.executable, target)

    digest = _sha256(target)
    (directory / "SHA256SUMS").write_text(
        f"{digest}  {asset}\n",
        encoding="utf-8",
    )
    return asset, digest


def _run(installer: str) -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        release = root / "release"
        install_dir = root / "install"
        release.mkdir()
        asset, expected = _prepare_release(release, installer)
        server, thread, base = _serve(release)
        try:
            env = os.environ.copy()
            env["AI_WORKFLOW_TEST_RELEASE_BASE"] = base

            if installer == "shell":
                env["AI_WORKFLOW_VERSION"] = VERSION
                env["AI_WORKFLOW_INSTALL_DIR"] = str(install_dir)
                command = ["sh", str(ROOT / "install.sh")]
                target = install_dir / "ai-workflow"
            else:
                executable = shutil.which("pwsh") or shutil.which("powershell")
                if not executable:
                    raise RuntimeError("PowerShell is required for the Windows installer smoke")
                command = [
                    executable,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "install.ps1"),
                    "-Version",
                    VERSION,
                    "-InstallDir",
                    str(install_dir),
                ]
                target = install_dir / "ai-workflow.exe"

            proc = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"installer failed:\n{proc.stdout}")
            if "SHA-256 verified." not in proc.stdout:
                raise RuntimeError(f"checksum confirmation missing:\n{proc.stdout}")
            if "gh attestation verify" not in proc.stdout:
                raise RuntimeError(f"provenance guidance missing:\n{proc.stdout}")
            if not target.is_file():
                raise RuntimeError(f"installer did not create {target}")
            if _sha256(target) != expected:
                raise RuntimeError("installed artifact hash differs from release artifact")

            if installer == "shell":
                smoke = subprocess.run(
                    [str(target), "--version"],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=10,
                )
                if smoke.returncode != 0 or VERSION not in smoke.stdout:
                    raise RuntimeError(f"installed binary smoke failed:\n{smoke.stdout}")

            print(f"bootstrap smoke passed: {installer} / {asset}")
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", choices=["shell", "powershell"], required=True)
    args = parser.parse_args()
    return _run(args.installer)


if __name__ == "__main__":
    raise SystemExit(main())
