from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.provider_sandbox import (
    ResourceLimits,
    SandboxPolicy,
    SandboxUnavailableError,
    build_sandbox_plan,
)


class ProviderSandboxPolicyTests(unittest.TestCase):
    def test_policy_validates_modes_backend_network_and_limits(self):
        policy = SandboxPolicy.from_mapping(
            {
                "mode": "required",
                "backend": "bubblewrap",
                "network": "deny",
                "limits": {
                    "cpu_seconds": 10,
                    "memory_mb": 256,
                    "file_size_mb": 32,
                    "open_files": 128,
                },
            }
        )
        self.assertEqual(policy.mode, "required")
        self.assertEqual(policy.backend, "bubblewrap")
        self.assertEqual(policy.network, "deny")
        self.assertEqual(policy.limits.cpu_seconds, 10)
        self.assertEqual(policy.limits.memory_mb, 256)
        self.assertTrue(policy.must_enforce)

        for raw in (
            {"mode": "unknown"},
            {"backend": "docker"},
            {"network": "maybe"},
            {"limits": {"cpu_seconds": 0}},
            {"limits": {"memory_mb": -1}},
            {"limits": {"open_files": True}},
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                SandboxPolicy.from_mapping(raw)

    def test_required_mode_fails_closed_when_backend_is_unavailable(self):
        policy = SandboxPolicy(mode="required")
        with patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=None,
        ):
            with self.assertRaises(SandboxUnavailableError):
                build_sandbox_plan(
                    policy,
                    ("/bin/echo", "ok"),
                    cwd=Path("/tmp"),
                    writable_paths=(),
                )

    def test_preferred_mode_may_fallback_only_without_hard_controls(self):
        with patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=None,
        ):
            soft = build_sandbox_plan(
                SandboxPolicy(mode="preferred"),
                ("/bin/echo", "ok"),
                cwd=Path("/tmp"),
                writable_paths=(),
            )
            self.assertFalse(soft.sandboxed)
            self.assertIsNone(soft.backend)
            self.assertEqual(soft.command, ("/bin/echo", "ok"))
            self.assertEqual(soft.fallback_reason, "backend_unavailable")

            for policy in (
                SandboxPolicy(mode="preferred", network="deny"),
                SandboxPolicy(
                    mode="preferred",
                    limits=ResourceLimits(memory_mb=128),
                ),
            ):
                with self.subTest(policy=policy):
                    with self.assertRaises(SandboxUnavailableError):
                        build_sandbox_plan(
                            policy,
                            ("/bin/echo", "ok"),
                            cwd=Path("/tmp"),
                            writable_paths=(),
                        )

    def test_bubblewrap_plan_is_read_only_drops_caps_and_denies_network(self):
        policy = SandboxPolicy(
            mode="required",
            backend="bubblewrap",
            network="deny",
            limits=ResourceLimits(
                cpu_seconds=5,
                memory_mb=128,
                file_size_mb=16,
                open_files=64,
            ),
        )
        with patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=Path("/usr/bin/bwrap"),
        ):
            plan = build_sandbox_plan(
                policy,
                ("/opt/provider/bin/tool", "--query"),
                cwd=Path("/tmp/runtime/cwd"),
                writable_paths=(
                    Path("/tmp/runtime/home"),
                    Path("/tmp/runtime/tmp"),
                    Path("/tmp/runtime/cwd"),
                ),
            )

        self.assertTrue(plan.sandboxed)
        self.assertEqual(plan.backend, "bubblewrap")
        args = list(plan.command)
        self.assertEqual(args[0], str(Path("/usr/bin/bwrap")))
        self.assertIn("--ro-bind", args)
        self.assertIn("--unshare-net", args)
        self.assertIn("--unshare-pid", args)
        self.assertIn("--unshare-ipc", args)
        self.assertIn("--unshare-uts", args)
        self.assertIn("--new-session", args)
        self.assertIn("--die-with-parent", args)
        self.assertIn("--cap-drop", args)
        self.assertIn("ALL", args)
        self.assertIn("--chdir", args)
        self.assertIn("ai_workflow.provider_sandbox_exec", args)
        self.assertTrue(plan.resource_limits_enforced)

    def test_off_mode_never_probes_backend(self):
        policy = SandboxPolicy(mode="off", network="host")
        with patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            side_effect=AssertionError("backend must not be probed"),
        ):
            plan = build_sandbox_plan(
                policy,
                ("/bin/echo", "ok"),
                cwd=Path("/tmp"),
                writable_paths=(),
            )
        self.assertFalse(plan.sandboxed)
        self.assertEqual(plan.command, ("/bin/echo", "ok"))


class ProviderSandboxRegistryTests(unittest.TestCase):
    def _registry(
        self,
        directory: Path,
        sandbox: dict[str, object] | None,
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
        if sandbox is not None:
            provider["sandbox"] = sandbox
        path = directory / "providers.json"
        path.write_text(
            json.dumps({"providers": {"test": provider}}),
            encoding="utf-8",
        )
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def test_sandbox_policy_is_owned_by_trusted_registry(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            registry = self._registry(
                Path(reg_td),
                {
                    "mode": "required",
                    "network": "deny",
                    "limits": {"memory_mb": 256},
                },
            )
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(registry)},
                clear=False,
            ):
                spec = resolve_project_provider(
                    root,
                    {"provider_id": "test"},
                    default_name="test",
                )
                self.assertEqual(spec.sandbox.mode, "required")
                self.assertEqual(spec.sandbox.network, "deny")
                self.assertEqual(spec.sandbox.limits.memory_mb, 256)

                with self.assertRaisesRegex(ValueError, "trusted fields"):
                    resolve_project_provider(
                        root,
                        {
                            "provider_id": "test",
                            "sandbox": {"mode": "off"},
                        },
                        default_name="test",
                    )

    def test_trusted_registry_defaults_to_sandbox_off_for_compatibility(self):
        from ai_workflow.provider_registry import resolve_project_provider

        with tempfile.TemporaryDirectory() as repo_td, tempfile.TemporaryDirectory() as reg_td:
            root = Path(repo_td)
            registry = self._registry(Path(reg_td), None)
            with patch.dict(
                os.environ,
                {"AI_WORKFLOW_PROVIDER_REGISTRY": str(registry)},
                clear=False,
            ):
                spec = resolve_project_provider(
                    root,
                    {"provider_id": "test"},
                    default_name="test",
                )
        self.assertEqual(spec.sandbox.mode, "off")


class ProviderSandboxRunnerTests(unittest.TestCase):
    def _request(self, root: Path):
        from ai_workflow.retrieval_contracts import RetrievalRequest

        return RetrievalRequest("q", root, 1, "semantic", 2)

    def _spec(self, sandbox: SandboxPolicy):
        from ai_workflow.provider_runner import CommandProviderSpec

        executable = Path(sys.executable).resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        code = (
            "import json,sys;"
            "sys.stdin.read();"
            "print(json.dumps({'items':[{'text':'sandbox-result','score':1.0}]}))"
        )
        return CommandProviderSpec(
            name="sandbox-test",
            command=(str(executable), "-c", code),
            timeout_seconds=2,
            max_output_bytes=4096,
            executable_trust="trusted_registry_digest",
            executable_sha256=digest,
            neutral_cwd=True,
            runtime_profile="restricted",
            sandbox=sandbox,
        )

    def test_required_sandbox_unavailable_returns_typed_failure_sync(self):
        from ai_workflow.provider_runner import run_command_provider

        spec = self._spec(SandboxPolicy(mode="required"))
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=None,
        ):
            result = run_command_provider(
                spec,
                self._request(Path(td)),
                source="external:sandbox-test",
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "sandbox_unavailable")
        self.assertFalse(result.sandboxed)
        self.assertEqual(result.sandbox_mode, "required")

    def test_required_sandbox_unavailable_returns_typed_failure_async(self):
        from ai_workflow.provider_runner import run_command_provider_async

        spec = self._spec(SandboxPolicy(mode="required"))
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=None,
        ):
            result = asyncio.run(
                run_command_provider_async(
                    spec,
                    self._request(Path(td)),
                    source="external:sandbox-test",
                )
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "sandbox_unavailable")
        self.assertFalse(result.sandboxed)
        self.assertEqual(result.sandbox_mode, "required")

    def test_preferred_fallback_is_visible_in_typed_result(self):
        from ai_workflow.provider_runner import run_command_provider

        spec = self._spec(SandboxPolicy(mode="preferred"))
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.provider_sandbox._resolve_bubblewrap",
            return_value=None,
        ):
            result = run_command_provider(
                spec,
                self._request(Path(td)),
                source="external:sandbox-test",
            )

        self.assertTrue(result.ok, result.error)
        self.assertFalse(result.sandboxed)
        self.assertEqual(result.sandbox_mode, "preferred")
        self.assertIsNone(result.sandbox_backend)
        self.assertEqual(result.sandbox_fallback_reason, "backend_unavailable")


if __name__ == "__main__":
    unittest.main()
