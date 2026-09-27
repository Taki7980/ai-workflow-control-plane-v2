import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.deployment_state import (
    STATE_LOCK_LEASE_SECONDS,
    _host_fingerprint,
    _recover_stale_lock,
    _state_lock,
)


class DeploymentLockRecoveryTests(unittest.TestCase):
    @unittest.skipIf(
        os.name == "nt",
        "portable PID liveness probe is POSIX-only",
    )
    def test_expired_lock_owned_by_live_local_pid_is_not_stolen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "active.json"
            lock = path.with_name(path.name + ".lock")
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps(
                    {
                        "token": "live-owner",
                        "pid": os.getpid(),
                        "host_fingerprint": _host_fingerprint(),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stale_time = time.time() - STATE_LOCK_LEASE_SECONDS - 10
            os.utime(lock, (stale_time, stale_time))

            with self.assertRaises(RuntimeError):
                with _state_lock(path):
                    pass

            self.assertTrue(lock.exists())

    def test_expired_dead_owner_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "active.json"
            lock = path.with_name(path.name + ".lock")
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps(
                    {
                        "token": "dead-owner",
                        "pid": 999999,
                        "host_fingerprint": _host_fingerprint(),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stale_time = time.time() - STATE_LOCK_LEASE_SECONDS - 10
            os.utime(lock, (stale_time, stale_time))

            with patch(
                "ai_workflow.deployment_state._pid_is_alive",
                return_value=False,
            ):
                with _state_lock(path):
                    owner = json.loads(
                        (lock / "owner.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertNotEqual(owner["token"], "dead-owner")

            self.assertFalse(lock.exists())

    def test_fresh_local_lock_is_not_stolen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "active.json"
            lock = path.with_name(path.name + ".lock")
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps({"token": "active-owner"}) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                with _state_lock(path):
                    pass

            self.assertTrue(lock.exists())


if __name__ == "__main__":
    unittest.main()
