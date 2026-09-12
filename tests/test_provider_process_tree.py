from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock, patch


class ProviderProcessTreeTests(unittest.TestCase):
    def test_posix_provider_launches_in_new_session(self) -> None:
        from ai_workflow import provider_runner

        with patch.object(provider_runner.os, "name", "posix"):
            self.assertEqual(
                provider_runner._provider_process_group_kwargs(),
                {"start_new_session": True},
            )

    def test_windows_provider_launches_in_new_process_group(self) -> None:
        from ai_workflow import provider_runner

        with patch.object(provider_runner.os, "name", "nt"), patch.object(
            provider_runner.subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0x00000200,
            create=True,
        ):
            self.assertEqual(
                provider_runner._provider_process_group_kwargs(),
                {"creationflags": 0x00000200},
            )

    def test_posix_termination_kills_process_group(self) -> None:
        from ai_workflow import provider_runner

        proc = Mock()
        proc.pid = 4242
        proc.returncode = None

        with patch.object(provider_runner.os, "name", "posix"), patch.object(
            provider_runner.os,
            "killpg",
            create=True,
        ) as killpg, patch.object(
            provider_runner.signal,
            "SIGKILL",
            9,
            create=True,
        ):
            provider_runner._terminate_provider_tree(proc)

        killpg.assert_called_once_with(4242, 9)
        proc.kill.assert_not_called()

    def test_windows_termination_uses_taskkill_tree(self) -> None:
        from ai_workflow import provider_runner

        proc = Mock()
        proc.pid = 31337
        proc.returncode = None

        with patch.object(provider_runner.os, "name", "nt"), patch.object(
            provider_runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ) as run:
            provider_runner._terminate_provider_tree(proc)

        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertEqual(
            argv,
            ["taskkill", "/PID", "31337", "/T", "/F"],
        )
        proc.kill.assert_not_called()

    def test_tree_termination_falls_back_to_direct_kill(self) -> None:
        from ai_workflow import provider_runner

        proc = Mock()
        proc.pid = 99
        proc.returncode = None

        with patch.object(provider_runner.os, "name", "posix"), patch.object(
            provider_runner.os,
            "killpg",
            side_effect=OSError("gone"),
            create=True,
        ), patch.object(
            provider_runner.signal,
            "SIGKILL",
            9,
            create=True,
        ):
            provider_runner._terminate_provider_tree(proc)

        proc.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
