import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is not installed")
class PowerShellTests(unittest.TestCase):
    def test_index_wrapper_forwards_incremental(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "generate-index.ps1"
            shutil.copyfile(Path(__file__).parents[1] / "ai-workspace/scripts/generate-index.ps1", script)
            (root / "_invoke.ps1").write_text(
                "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Forwarded)\n"
                "ConvertTo-Json -InputObject @($Forwarded) -Compress\n",
                encoding="utf-8",
            )
            for switches, expected in (([], ["index"]), (["-Incremental"], ["index", "--incremental"])):
                with self.subTest(switches=switches):
                    result = subprocess.run(
                        [POWERSHELL, "-NoProfile", "-File", str(script), *switches],
                        capture_output=True, text=True, check=True, timeout=30,
                    )
                    self.assertEqual(json.loads(result.stdout), expected)
