from __future__ import annotations

import argparse
import copy
import gzip
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def _safe_member_name(name: str) -> bool:
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
    ):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and all(part not in {"", ".", ".."} for part in parts)


def _normalized_mode(member: tarfile.TarInfo) -> int:
    if member.isdir():
        return 0o755
    if member.isfile():
        return 0o755 if member.mode & 0o100 else 0o644
    raise ValueError(f"unsupported sdist member type: {member.name}")


def normalize_sdist(path: Path, *, source_date_epoch: int) -> None:
    if source_date_epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be non-negative")

    source = path.resolve()
    if not source.is_file() or not source.name.endswith(".tar.gz"):
        raise ValueError("sdist must be an existing .tar.gz file")

    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("sdist archive must not be empty")

        top_levels: set[str] = set()
        normalized: list[tuple[tarfile.TarInfo, bytes | None]] = []
        seen: set[str] = set()

        for member in sorted(members, key=lambda item: item.name):
            if not _safe_member_name(member.name):
                raise ValueError(f"unsafe sdist member path: {member.name}")
            if member.name in seen:
                raise ValueError(f"duplicate sdist member path: {member.name}")
            seen.add(member.name)
            top_levels.add(PurePosixPath(member.name).parts[0])

            if not (member.isfile() or member.isdir()):
                raise ValueError(
                    "sdist contains unsupported link/device member: "
                    + member.name
                )

            payload: bytes | None = None
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(
                        f"unable to read sdist member: {member.name}"
                    )
                payload = extracted.read()

            info = copy.copy(member)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = source_date_epoch
            info.mode = _normalized_mode(info)
            info.devmajor = 0
            info.devminor = 0
            info.pax_headers = {}
            normalized.append((info, payload))

    if len(top_levels) != 1:
        raise ValueError("sdist must contain exactly one top-level directory")

    names = {info.name for info, _ in normalized}
    top = next(iter(top_levels))
    expected_top = source.name.removesuffix(".tar.gz")
    if top != expected_top:
        raise ValueError(
            "sdist top-level directory must match archive filename"
        )
    if f"{top}/pyproject.toml" not in names:
        raise ValueError("sdist is missing pyproject.toml")
    if f"{top}/PKG-INFO" not in names:
        raise ValueError("sdist is missing PKG-INFO")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=source.parent,
            prefix=f".{source.name}.",
            suffix=".tmp",
            delete=False,
        ) as raw:
            temp_path = Path(raw.name)
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw,
                mtime=source_date_epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                    pax_headers={},
                ) as output:
                    for info, payload in normalized:
                        if payload is None:
                            output.addfile(info)
                        else:
                            output.addfile(info, BytesIO(payload))
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temp_path, source)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    with tarfile.open(source, "r:gz") as verified:
        verified_members = verified.getmembers()
        if not verified_members:
            raise ValueError("normalized sdist is unreadable")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a project sdist into deterministic POSIX pax tar.gz "
            "metadata using SOURCE_DATE_EPOCH."
        )
    )
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    args = parser.parse_args()

    normalize_sdist(
        args.sdist,
        source_date_epoch=args.source_date_epoch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
