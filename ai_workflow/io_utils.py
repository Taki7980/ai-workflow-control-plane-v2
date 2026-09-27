from __future__ import annotations

import errno
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


_UNSUPPORTED_DIRECTORY_FSYNC = {
    errno.EBADF,
    errno.EINVAL,
}
if hasattr(errno, "ENOTSUP"):
    _UNSUPPORTED_DIRECTORY_FSYNC.add(errno.ENOTSUP)
if hasattr(errno, "EOPNOTSUPP"):
    _UNSUPPORTED_DIRECTORY_FSYNC.add(errno.EOPNOTSUPP)


def fsync_directory(path: Path) -> bool:
    """Persist directory-entry changes when the platform exposes directory fsync.

    Windows does not expose a portable directory-fsync primitive through
    Python's os module, so the function reports False there rather than
    pretending to provide a durability guarantee it cannot enforce.
    """

    directory = Path(path)
    if os.name == "nt":
        return False

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(directory, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC:
                return False
            raise
    finally:
        os.close(fd)
    return True


def _write_and_fsync(
    fd: int,
    content: str,
    *,
    encoding: str,
) -> None:
    with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write through a sibling temp file, fsync, replace, then sync the parent."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        _write_and_fsync(fd, content, encoding=encoding)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def atomic_create_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Publish a new immutable file only after its complete contents are durable.

    A sibling temp file is fully written and fsynced first. A hard-link publish
    then atomically claims the final name without overwriting an existing file.
    If the final name already exists, FileExistsError is preserved.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        _write_and_fsync(fd, content, encoding=encoding)
        os.link(temporary, path)
        fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
) -> None:
    atomic_write_text(
        path,
        json.dumps(
            value,
            indent=indent,
            ensure_ascii=False,
            sort_keys=sort_keys,
        )
        + "\n",
    )


def atomic_create_json(
    path: Path,
    value: Any,
    *,
    indent: int = 2,
    sort_keys: bool = False,
) -> None:
    atomic_create_text(
        path,
        json.dumps(
            value,
            indent=indent,
            ensure_ascii=False,
            sort_keys=sort_keys,
        )
        + "\n",
    )


def atomic_write_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
) -> None:
    atomic_write_text(
        path,
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in rows
        ),
    )
