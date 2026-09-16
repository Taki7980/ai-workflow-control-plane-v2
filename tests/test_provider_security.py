from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ProviderLaunchSecurityTests(unittest.TestCase):
    def _registry_spec(
        self,
        repo_root: Path,
        registry_root: Path,
        *,
        executable: Path | None = None,
        command_tail: list[str] | None = None,
        extra: dict | None = None,
        project_extra: dict | None = None,
    ):
        from ai_workflow.provider_registry import resolve_project_provider

        executable = (executable or Path(sys.executable)).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        registry_path = registry_root / "providers.json"
        provider = {
            "command": [str(executable), *(command_tail or [])],
            "sha256": digest,
            "env_allowlist": ["AI_WORKFLOW_PROVIDER_TEST_SECRET"],
            "timeout_seconds": 3,
            "max_output_bytes": 8192,
        }
        provider.update(extra or {})
        registry_path.write_text(
            json.dumps({"providers": {"secure-test": provider}}),
            encoding="utf-8",
        )
        project = {
            "name": "secure-test",
            "provider_id": "secure-test",
        }
        project.update(project_extra or {})
        with patch.dict(
            os.environ,
            {"AI_WORKFLOW_PROVIDER_REGISTRY": str(registry_path)},
            clear=False,
        ):
            return resolve_project_provider(
                repo_root,
                project,
                default_name="secure-test",
            )

    def _request(self, root: Path):
        from ai_workflow.retrieval_contracts import RetrievalRequest

        return RetrievalRequest(
            query="find payment handler",
            root=root,
            limit=2,
            intent="semantic",
            timeout_seconds=2,
        )

    def test_trusted_registry_spec_carries_launch_security_policy(self) -> None:
        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as registry_td:
            root = Path(repo_td)
            spec = self._registry_spec(root, Path(registry_td))
            expected = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()

            self.assertEqual(spec.executable_sha256, expected)
            self.assertTrue(spec.neutral_cwd)
            self.assertEqual(spec.max_stderr_bytes, 64 * 1024)

    def test_trusted_provider_digest_is_reverified_immediately_before_sync_launch(self) -> None:
        from ai_workflow.provider_runner import run_command_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as registry_td:
            root = Path(repo_td)
            registry_root = Path(registry_td)
            executable = registry_root / Path(sys.executable).name
            shutil.copy2(sys.executable, executable)
            spec = self._registry_spec(
                root,
                registry_root,
                executable=executable,
                command_tail=["-c", "import sys; sys.stdin.read(); print('[]')"],
            )

            with executable.open("ab") as handle:
                handle.write(b"provider-drift")

            result = run_command_provider(
                spec,
                self._request(root),
                source="external:secure-test",
            )

            self.assertEqual(result.error_kind, "provider_trust")
            self.assertIn("digest", result.error or "")

    def test_trusted_provider_uses_ephemeral_neutral_cwd(self) -> None:
        from ai_workflow.provider_runner import run_command_provider

        code = (
            "import json,os,sys;"
            "sys.stdin.read();"
            "print(json.dumps({'items':[{'text':os.getcwd(),'score':1.0}]}))"
        )
        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as registry_td:
            root = Path(repo_td).resolve()
            spec = self._registry_spec(
                root,
                Path(registry_td),
                command_tail=["-c", code],
            )

            result = run_command_provider(
                spec,
                self._request(root),
                source="external:secure-test",
            )

            self.assertIsNone(result.error)
            cwd = Path(result.items[0].text).resolve()
            self.assertNotEqual(cwd, root)
            self.assertNotEqual(cwd, Path(sys.executable).resolve().parent)
            self.assertFalse(cwd.exists())

    def test_repository_cannot_override_trusted_launch_security_policy(self) -> None:
        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as registry_td:
            root = Path(repo_td)
            for field, value in (
                ("neutral_cwd", False),
                ("max_stderr_bytes", 1024 * 1024),
                ("executable_sha256", "0" * 64),
            ):
                with self.subTest(field=field):
                    with self.assertRaisesRegex(
                        ValueError,
                        "trusted fields",
                    ):
                        self._registry_spec(
                            root,
                            Path(registry_td),
                            project_extra={field: value},
                        )

    def test_trusted_registry_rejects_symlinked_executable_path(self) -> None:
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as registry_td:
            root = Path(repo_td)
            registry_root = Path(registry_td)
            link = registry_root / ("provider.exe" if os.name == "nt" else "provider")
            try:
                link.symlink_to(Path(sys.executable).resolve())
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            digest = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
            registry_path = registry_root / "providers.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "secure-test": {
                                "command": [str(link)],
                                "sha256": digest,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(registry_path)},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    resolve_project_provider(
                        root,
                        {"provider_id": "secure-test"},
                        default_name="secure-test",
                    )

    def test_sync_stderr_is_bounded_redacted_and_typed(self) -> None:
        from ai_workflow.provider_runner import CommandProviderSpec, run_command_provider

        secret = "super-secret-provider-token"
        code = (
            "import os,sys;"
            "sys.stdin.read();"
            "sys.stderr.write('x'*4096);"
            "sys.stderr.write('\\nTOKEN='+os.environ['AI_WORKFLOW_PROVIDER_TEST_SECRET']);"
            "sys.stderr.write('\\nAuthorization: Bearer '+os.environ['AI_WORKFLOW_PROVIDER_TEST_SECRET']);"
            "sys.stderr.flush();"
            "sys.exit(7)"
        )
        spec = CommandProviderSpec(
            name="stderr-sync",
            command=(sys.executable, "-c", code),
            timeout_seconds=2,
            max_output_bytes=4096,
            env_allowlist=("AI_WORKFLOW_PROVIDER_TEST_SECRET",),
            max_stderr_bytes=256,
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {"AI_WORKFLOW_PROVIDER_TEST_SECRET": secret},
            clear=False,
        ):
            result = run_command_provider(
                spec,
                self._request(Path(td)),
                source="external:stderr-sync",
            )

        self.assertEqual(result.error_kind, "exit")
        self.assertTrue(result.stderr_truncated)
        self.assertIsNotNone(result.stderr_tail)
        self.assertLessEqual(len((result.stderr_tail or "").encode("utf-8")), 256)
        self.assertNotIn(secret, result.stderr_tail or "")
        self.assertIn("[REDACTED]", result.stderr_tail or "")
        self.assertEqual(result.items, ())
        error = result.error_dict() or {}
        self.assertEqual(error["stderr_tail"], result.stderr_tail)
        self.assertTrue(error["stderr_truncated"])

    def test_async_runner_enforces_launch_digest_and_stderr_policy(self) -> None:
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider_async,
        )

        secret = "async-provider-secret"
        code = (
            "import os,sys;"
            "sys.stdin.read();"
            "sys.stderr.write('y'*2048);"
            "sys.stderr.write('\\npassword='+os.environ['AI_WORKFLOW_PROVIDER_TEST_SECRET']);"
            "sys.stderr.flush();"
            "sys.exit(9)"
        )
        spec = CommandProviderSpec(
            name="stderr-async",
            command=(sys.executable, "-c", code),
            timeout_seconds=2,
            max_output_bytes=4096,
            env_allowlist=("AI_WORKFLOW_PROVIDER_TEST_SECRET",),
            max_stderr_bytes=192,
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {"AI_WORKFLOW_PROVIDER_TEST_SECRET": secret},
            clear=False,
        ):
            result = asyncio.run(
                run_command_provider_async(
                    spec,
                    self._request(Path(td)),
                    source="external:stderr-async",
                )
            )

        self.assertEqual(result.error_kind, "exit")
        self.assertTrue(result.stderr_truncated)
        self.assertLessEqual(len((result.stderr_tail or "").encode("utf-8")), 192)
        self.assertNotIn(secret, result.stderr_tail or "")
        self.assertIn("[REDACTED]", result.stderr_tail or "")


if __name__ == "__main__":
    unittest.main()
