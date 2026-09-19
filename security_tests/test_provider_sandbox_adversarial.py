from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.provider_sandbox import SandboxPolicy


class ProviderSandboxAdversarialTests(unittest.TestCase):
    def _request(self, root: Path):
        from ai_workflow.retrieval_contracts import RetrievalRequest

        return RetrievalRequest(
            "q",
            root,
            1,
            "semantic",
            2,
        )

    def test_required_sandbox_unavailable_never_executes_provider(self):
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sentinel = root / "must-not-exist.txt"
            code = (
                "from pathlib import Path;"
                f"Path({str(sentinel)!r}).write_text('executed');"
                "print('[]')"
            )
            spec = CommandProviderSpec(
                name="required-sandbox",
                command=(sys.executable, "-c", code),
                timeout_seconds=1,
                max_output_bytes=1024,
                sandbox=SandboxPolicy(mode="required"),
            )
            with patch(
                "ai_workflow.provider_sandbox._resolve_bubblewrap",
                return_value=None,
            ):
                result = run_command_provider(
                    spec,
                    self._request(root),
                    source="external:required-sandbox",
                )

            self.assertEqual(result.error_kind, "sandbox_unavailable")
            self.assertFalse(sentinel.exists())

    def test_network_deny_policy_never_silently_falls_back(self):
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sentinel = root / "network-policy-bypass.txt"
            code = (
                "from pathlib import Path;"
                f"Path({str(sentinel)!r}).write_text('executed');"
                "print('[]')"
            )
            spec = CommandProviderSpec(
                name="network-deny",
                command=(sys.executable, "-c", code),
                timeout_seconds=1,
                max_output_bytes=1024,
                sandbox=SandboxPolicy(
                    mode="preferred",
                    network="deny",
                ),
            )
            with patch(
                "ai_workflow.provider_sandbox._resolve_bubblewrap",
                return_value=None,
            ):
                result = run_command_provider(
                    spec,
                    self._request(root),
                    source="external:network-deny",
                )

            self.assertEqual(result.error_kind, "sandbox_unavailable")
            self.assertFalse(sentinel.exists())

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "bubblewrap integration is Linux-only",
    )
    def test_real_bubblewrap_backend_blocks_host_writes_when_available(self):
        from ai_workflow.provider_runner import (
            CommandProviderSpec,
            run_command_provider,
        )
        from ai_workflow.provider_sandbox import _resolve_bubblewrap

        backend = _resolve_bubblewrap("deny")
        if backend is None:
            self.skipTest("usable bubblewrap backend is not installed")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            outside = root / "outside-write.txt"
            code = (
                "import json,sys;"
                "from pathlib import Path;"
                "sys.stdin.read();"
                f"p=Path({str(outside)!r});"
                "ok=True;"
                "\ntry:\n p.write_text('escape')\n"
                "except OSError:\n ok=False\n"
                "print(json.dumps({'items':[{'text':str(ok),'score':1.0}]}))"
            )
            spec = CommandProviderSpec(
                name="bubblewrap-write",
                command=(sys.executable, "-c", code),
                timeout_seconds=2,
                max_output_bytes=4096,
                neutral_cwd=True,
                runtime_profile="restricted",
                sandbox=SandboxPolicy(
                    mode="required",
                    backend="bubblewrap",
                    network="deny",
                ),
            )
            result = run_command_provider(
                spec,
                self._request(root),
                source="external:bubblewrap-write",
            )

            self.assertTrue(result.ok, result.error)
            self.assertTrue(result.sandboxed)
            self.assertEqual(result.sandbox_backend, "bubblewrap")
            self.assertEqual(result.sandbox_network, "deny")
            self.assertEqual(result.items[0].text, "False")
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
