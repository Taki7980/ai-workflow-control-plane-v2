import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from ai_workflow.deployment_state import (
    STATE_LOCK_LEASE_SECONDS,
    _state_lock,
)


class DeploymentLockRecoveryTests(unittest.TestCase):
    def test_stale_local_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "active.json"
            lock = path.with_name(path.name + ".lock")
            lock.mkdir()
            (lock / "owner.json").write_text(
                json.dumps({"token": "dead-owner"}) + "\n",
                encoding="utf-8",
            )
            stale_time = time.time() - STATE_LOCK_LEASE_SECONDS - 10
            os.utime(lock, (stale_time, stale_time))

            with _state_lock(path):
                owner = json.loads(
                    (lock / "owner.json").read_text(encoding="utf-8")
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
