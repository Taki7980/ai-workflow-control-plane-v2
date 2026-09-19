from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ProviderRuntimeProfileTests(unittest.TestCase):
    def _registry(
        self,
        directory: Path,
        *,
        runtime_profile: str | None = None,
    ) -> Path:
        executable = Path(sys.executable).resolve()
        provider: dict[str, object] = {
            "command": [
                str(executable),
                "-c",
                "import json,sys;sys.stdin.read();print(json.dumps({'items': []}))",
            ],
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        }
        if runtime_profile is not None:
            provider["runtime_profile"] = runtime_profile
        path = directory / "providers.json"
        path.write_text(
            json.dumps({"providers": {"test": provider}}),
            encoding="utf-8",
        )
        if os.name != "nt":
            path.chmod(0o600)
        return path

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable")
    def test_registry_rejects_group_or_world_writable_trust_anchor(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            path = self._registry(Path(reg_td))
            path.chmod(0o666)
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(path)},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "writable by group or others"):
                    resolve_project_provider(
                        root,
                        {"provider_id": "test"},
                        default_name="test",
                    )

    @unittest.skipIf(os.name == "nt", "POSIX ownership is not portable")
    def test_registry_rejects_unexpected_owner_when_uid_is_available(self):
        from ai_workflow.provider_registry import resolve_project_provider

        if not hasattr(os, "getuid"):
            self.skipTest("uid ownership unavailable")
        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            path = self._registry(Path(reg_td))
            actual_owner = path.stat().st_uid
            if actual_owner == 0:
                self.skipTest("root-owned trust anchor is intentionally accepted")
            with (
                patch.dict(
                    os.environ,
                    {"AI_WORKFLOW_PROVIDER_REGISTRY": str(path)},
                    clear=False,
                ),
                patch(
                    "ai_workflow.provider_registry.os.getuid",
                    return_value=actual_owner + 1,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "must be owned by"):
                    resolve_project_provider(
                        root,
                        {"provider_id": "test"},
                        default_name="test",
                    )

    def test_registry_symlink_is_not_accepted_as_trust_anchor(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            target = self._registry(Path(reg_td))
            link = Path(reg_td) / "providers-link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(link)},
                clear=False,
            ):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    resolve_project_provider(
                        root,
                        {"provider_id": "test"},
                        default_name="test",
                    )

    def test_trusted_registry_defaults_to_restricted_runtime_profile(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            path = self._registry(Path(reg_td))
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(path)},
                clear=False,
            ):
                spec = resolve_project_provider(
                    root,
                    {"provider_id": "test"},
                    default_name="test",
                )
        self.assertEqual(spec.runtime_profile, "restricted")

    def test_compatibility_profile_must_come_from_trusted_registry(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            path = self._registry(Path(reg_td), runtime_profile="compatibility")
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(path)},
                clear=False,
            ):
                spec = resolve_project_provider(
                    root,
                    {"provider_id": "test"},
                    default_name="test",
                )
                self.assertEqual(spec.runtime_profile, "compatibility")

                with self.assertRaisesRegex(ValueError, "trusted fields"):
                    resolve_project_provider(
                        root,
                        {
                            "provider_id": "test",
                            "runtime_profile": "compatibility",
                        },
                        default_name="test",
                    )

    def test_restricted_runtime_gets_ephemeral_home_temp_and_minimal_path(self):
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider,
        )
        from ai_workflow.retrieval_contracts import RetrievalRequest

        executable = Path(sys.executable).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        code = (
            "import json,os,sys;"
            "sys.stdin.read();"
            "keys=['HOME','USERPROFILE','TMPDIR','TEMP','TMP','PATH',"
            "'AWS_PROFILE','EXPLICIT_PROVIDER_TOKEN','PYTHONUTF8','PYTHONIOENCODING'];"
            "print(json.dumps({'items':[{'text':json.dumps({k:os.environ.get(k) for k in keys}),"
            "'score':1.0}]}))"
        )
        spec = CommandProviderSpec(
            name="restricted-runtime",
            command=(str(executable), "-c", code),
            timeout_seconds=2,
            max_output_bytes=8192,
            env_allowlist=("EXPLICIT_PROVIDER_TOKEN",),
            executable_trust="trusted_registry_digest",
            executable_sha256=digest,
            neutral_cwd=True,
            runtime_profile="restricted",
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {
                "HOME": str(Path(td) / "ambient-home"),
                "USERPROFILE": str(Path(td) / "ambient-profile"),
                "TMPDIR": str(Path(td) / "ambient-tmp"),
                "TEMP": str(Path(td) / "ambient-temp"),
                "TMP": str(Path(td) / "ambient-tmp2"),
                "PATH": str(Path(td) / "attacker-bin"),
                "AWS_PROFILE": "production",
                "EXPLICIT_PROVIDER_TOKEN": "allowed-token",
            },
            clear=False,
        ):
            result = run_command_provider(
                spec,
                RetrievalRequest("q", Path(td), 1, "semantic", 2),
                source="external:restricted-runtime",
            )

        self.assertTrue(result.ok, result.error)
        env = json.loads(result.items[0].text)
        self.assertIsNone(env["AWS_PROFILE"])
        self.assertEqual(env["EXPLICIT_PROVIDER_TOKEN"], "allowed-token")
        self.assertEqual(
            env["PATH"],
            str(executable.parent),
        )
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

        home = Path(env["HOME"])
        self.assertEqual(env["USERPROFILE"], str(home))
        temp_paths = {
            Path(env["TMPDIR"]),
            Path(env["TEMP"]),
            Path(env["TMP"]),
        }
        self.assertEqual(len(temp_paths), 1)
        temp_path = next(iter(temp_paths))
        self.assertNotEqual(home, Path(td) / "ambient-home")
        self.assertNotEqual(temp_path, Path(td) / "ambient-tmp")
        self.assertFalse(home.exists())
        self.assertFalse(temp_path.exists())

    def test_compatibility_profile_preserves_legacy_safe_environment(self):
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider,
        )
        from ai_workflow.retrieval_contracts import RetrievalRequest

        executable = Path(sys.executable).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        code = (
            "import json,os,sys;"
            "sys.stdin.read();"
            "print(json.dumps({'items':[{'text':json.dumps({"
            "'HOME':os.environ.get('HOME'),'PATH':os.environ.get('PATH')}),"
            "'score':1.0}]}))"
        )
        spec = CommandProviderSpec(
            name="compat-runtime",
            command=(str(executable), "-c", code),
            timeout_seconds=2,
            max_output_bytes=8192,
            executable_trust="trusted_registry_digest",
            executable_sha256=digest,
            neutral_cwd=True,
            runtime_profile="compatibility",
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            {
                "HOME": str(Path(td) / "legacy-home"),
                "PATH": os.environ.get("PATH", ""),
            },
            clear=False,
        ):
            expected_home = os.environ["HOME"]
            expected_path = os.environ["PATH"]
            result = run_command_provider(
                spec,
                RetrievalRequest("q", Path(td), 1, "semantic", 2),
                source="external:compat-runtime",
            )

        self.assertTrue(result.ok, result.error)
        env = json.loads(result.items[0].text)
        self.assertEqual(env["HOME"], expected_home)
        self.assertEqual(env["PATH"], expected_path)


if __name__ == "__main__":
    unittest.main()
