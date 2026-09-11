from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from ai_workflow.repository_registry import refresh_registry, registry_path


class RegistryPathSecurityTests(unittest.TestCase):
    def test_default_registry_stays_inside_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            resolved = registry_path(root)
            resolved.relative_to(root)
            self.assertEqual(
                resolved,
                root / "ai-workspace/config/repositories.json",
            )

    def test_nested_workspace_relative_registry_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            config = {"workspace": {"registry": "state/registry.json"}}
            self.assertEqual(registry_path(root, config), root / "state/registry.json")

    def test_parent_traversal_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            config = {"workspace": {"registry": "../outside.json"}}
            with self.assertRaisesRegex(ValueError, "workspace.registry"):
                registry_path(root, config)

    def test_absolute_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            outside = root.parent / "outside-registry.json"
            config = {"workspace": {"registry": str(outside)}}
            with self.assertRaisesRegex(ValueError, "workspace.registry"):
                registry_path(root, config)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside_td:
            root = Path(td).resolve()
            outside = Path(outside_td).resolve()
            link = root / "escape"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable on this platform")
            config = {"workspace": {"registry": "escape/registry.json"}}
            with self.assertRaisesRegex(ValueError, "workspace.registry"):
                registry_path(root, config)

    def test_refresh_rejects_escape_before_creating_external_file_or_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            outside = root.parent / f"{root.name}-outside-registry.json"
            lock = Path(f"{outside}.lock")
            outside.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
            config = {"workspace": {"registry": str(outside)}}
            try:
                with self.assertRaisesRegex(ValueError, "workspace.registry"):
                    refresh_registry(root, config=config)
                self.assertFalse(outside.exists())
                self.assertFalse(lock.exists())
            finally:
                outside.unlink(missing_ok=True)
                lock.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
