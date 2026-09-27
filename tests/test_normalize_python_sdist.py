from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.normalize_python_sdist import normalize_sdist


class NormalizePythonSdistTests(unittest.TestCase):
    def _write_archive(
        self,
        path: Path,
        *,
        gzip_mtime: int,
        member_mtime: int,
        uid: int,
        reverse: bool = False,
        unsafe_member: tarfile.TarInfo | None = None,
    ) -> None:
        entries = [
            ("ai_workflow_control_plane-2.3.0", None, 0o755),
            (
                "ai_workflow_control_plane-2.3.0/pyproject.toml",
                b"[build-system]\nrequires = []\n",
                0o644,
            ),
            (
                "ai_workflow_control_plane-2.3.0/PKG-INFO",
                b"Metadata-Version: 2.4\nName: ai-workflow-control-plane\nVersion: 2.3.0\n",
                0o644,
            ),
            (
                "ai_workflow_control_plane-2.3.0/ai_workflow/tool.py",
                b"print('ok')\n",
                0o755,
            ),
        ]
        if reverse:
            entries.reverse()

        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="volatile-name.tar",
                mode="wb",
                fileobj=raw,
                mtime=gzip_mtime,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for name, payload, mode in entries:
                        info = tarfile.TarInfo(name)
                        info.mtime = member_mtime
                        info.uid = uid
                        info.gid = uid + 1
                        info.uname = f"user-{uid}"
                        info.gname = f"group-{uid}"
                        info.mode = mode
                        if payload is None:
                            info.type = tarfile.DIRTYPE
                            archive.addfile(info)
                        else:
                            info.size = len(payload)
                            archive.addfile(info, io.BytesIO(payload))
                    if unsafe_member is not None:
                        archive.addfile(unsafe_member)

    def test_metadata_and_order_differences_normalize_byte_identically(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            name = "ai_workflow_control_plane-2.3.0.tar.gz"
            first = first_dir / name
            second = second_dir / name
            self._write_archive(
                first,
                gzip_mtime=10,
                member_mtime=20,
                uid=1000,
            )
            self._write_archive(
                second,
                gzip_mtime=30,
                member_mtime=40,
                uid=2000,
                reverse=True,
            )
            self.assertNotEqual(first.read_bytes(), second.read_bytes())

            normalize_sdist(first, source_date_epoch=1_700_000_000)
            normalize_sdist(second, source_date_epoch=1_700_000_000)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first, "r:gz") as archive:
                members = archive.getmembers()

        self.assertEqual(
            [member.name for member in members],
            sorted(member.name for member in members),
        )
        for member in members:
            self.assertEqual(member.mtime, 1_700_000_000)
            self.assertEqual(member.uid, 0)
            self.assertEqual(member.gid, 0)
            self.assertEqual(member.uname, "")
            self.assertEqual(member.gname, "")
            self.assertEqual(member.pax_headers, {})
            if member.isdir():
                self.assertEqual(member.mode, 0o755)
            elif member.name.endswith("tool.py"):
                self.assertEqual(member.mode, 0o755)
            else:
                self.assertEqual(member.mode, 0o644)

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = (
                Path(td)
                / "ai_workflow_control_plane-2.3.0.tar.gz"
            )
            unsafe = tarfile.TarInfo("../escape")
            unsafe.size = 0
            self._write_archive(
                path,
                gzip_mtime=1,
                member_mtime=1,
                uid=1,
                unsafe_member=unsafe,
            )

            with self.assertRaisesRegex(ValueError, "unsafe sdist member path"):
                normalize_sdist(path, source_date_epoch=1)

    def test_links_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = (
                Path(td)
                / "ai_workflow_control_plane-2.3.0.tar.gz"
            )
            link = tarfile.TarInfo(
                "ai_workflow_control_plane-2.3.0/link"
            )
            link.type = tarfile.SYMTYPE
            link.linkname = "pyproject.toml"
            self._write_archive(
                path,
                gzip_mtime=1,
                member_mtime=1,
                uid=1,
                unsafe_member=link,
            )

            with self.assertRaisesRegex(
                ValueError,
                "unsupported link/device member",
            ):
                normalize_sdist(path, source_date_epoch=1)

    def test_archive_filename_must_match_top_level_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wrong-name-1.0.tar.gz"
            self._write_archive(
                path,
                gzip_mtime=1,
                member_mtime=1,
                uid=1,
            )

            with self.assertRaisesRegex(
                ValueError,
                "top-level directory must match",
            ):
                normalize_sdist(path, source_date_epoch=1)

    def test_required_sdist_metadata_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pkg-1.0.tar.gz"
            with path.open("wb") as raw:
                with gzip.GzipFile(
                    filename="",
                    mode="wb",
                    fileobj=raw,
                    mtime=1,
                ) as compressed:
                    with tarfile.open(
                        fileobj=compressed,
                        mode="w",
                        format=tarfile.PAX_FORMAT,
                    ) as archive:
                        payload = b"x"
                        info = tarfile.TarInfo("pkg-1.0/file.txt")
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))

            with self.assertRaisesRegex(ValueError, "pyproject.toml"):
                normalize_sdist(path, source_date_epoch=1)


if __name__ == "__main__":
    unittest.main()
