import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.io_utils import (
    atomic_create_json,
    atomic_write_text,
)


class IOCrashConsistencyTests(unittest.TestCase):
    def test_replace_failure_preserves_previous_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "state.json"
            path.write_text("old\n", encoding="utf-8")

            with patch(
                "ai_workflow.io_utils.os.replace",
                side_effect=OSError(errno.ENOSPC, "disk full"),
            ):
                with self.assertRaises(OSError):
                    atomic_write_text(path, "new\n")

            self.assertEqual(path.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(
                list(root.glob(f".{path.name}.*.tmp")),
                [],
            )

    def test_atomic_create_never_exposes_partial_final_name_on_publish_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "immutable.json"

            with patch(
                "ai_workflow.io_utils.os.link",
                side_effect=OSError(errno.ENOSPC, "disk full"),
            ):
                with self.assertRaises(OSError):
                    atomic_create_json(path, {"value": 1})

            self.assertFalse(path.exists())
            self.assertEqual(
                list(root.glob(f".{path.name}.*.tmp")),
                [],
            )

    def test_atomic_create_refuses_to_overwrite_existing_immutable_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "immutable.json"
            atomic_create_json(path, {"value": 1}, sort_keys=True)

            with self.assertRaises(FileExistsError):
                atomic_create_json(path, {"value": 2}, sort_keys=True)

            self.assertIn('"value": 1', path.read_text(encoding="utf-8"))

    def test_atomic_replace_requests_parent_directory_sync(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.txt"
            with patch(
                "ai_workflow.io_utils.fsync_directory",
                return_value=True,
            ) as sync:
                atomic_write_text(path, "durable")

            sync.assert_called_once_with(path.parent)


if __name__ == "__main__":
    unittest.main()
