from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SecurityCIContractTests(unittest.TestCase):
    def test_security_workflow_covers_required_gates(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "security.yml"
        ).read_text(encoding="utf-8")

        for required in (
            "python-security:",
            "secret-scan:",
            "container-scan:",
            "pip-audit --strict .",
            "ruff check --select S",
            "coverage report --fail-under=",
            "pip-licenses",
            "python -m unittest discover -s security_tests -v",
            "gitleaks_8.30.1_linux_x64.tar.gz",
            'version="0.74.0"',
            'asset="trivy_${version}_Linux-64bit.tar.gz"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)

        self.assertIn(
            "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
            workflow,
        )
        self.assertIn(
            "bc701c3c3ee8b9acbea2c23257e41381e3854888f51281616a6ba5dc96963821",
            workflow,
        )

    def test_security_tools_are_exactly_pinned(self) -> None:
        raw = (ROOT / "security" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        expected = {
            "coverage": "7.16.0",
            "hypothesis": "6.168.0",
            "pip-audit": "2.10.1",
            "pip-licenses": "5.5.5",
            "ruff": "0.16.7",
        }
        parsed: dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertRegex(line, r"^[a-z0-9-]+==[^=<>~!]+$")
            name, version = line.split("==", 1)
            parsed[name] = version
        self.assertEqual(parsed, expected)

    def test_security_workflow_uses_read_only_default_permissions(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "security.yml"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            workflow,
            re.compile(
                r"(?ms)^permissions:\n  contents: read\n",
            ),
        )


if __name__ == "__main__":
    unittest.main()
