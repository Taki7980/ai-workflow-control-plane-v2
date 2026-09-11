import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.telemetry import (
    OTLP_ALLOWED_HOSTS_ENV,
    OTLP_ENDPOINT_ENV,
    STORE_TASK_TEXT_ENV,
    TASK_FINGERPRINT_KEY_ENV,
    RetrievalTrace,
    _privacy_payload,
    trusted_otlp_endpoint,
    write_trace,
)


class TelemetrySecurityTests(unittest.TestCase):
    def setUp(self):
        self.trace = RetrievalTrace(
            "fix auth secret-token",
            "small",
            "low",
            "exact",
        )

    def test_project_config_cannot_opt_raw_task_text_into_persistence(self):
        config = {
            "context": {
                "telemetry": {
                    "store_task_text": True,
                    "include_task_text": True,
                }
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            payload = _privacy_payload(self.trace, config)
        self.assertNotIn("task", payload)
        self.assertIn("task_fingerprint", payload)

    def test_runtime_opt_in_may_store_redacted_task_text(self):
        config = {
            "context": {
                "telemetry": {"redact_patterns": ["secret-token"]}
            }
        }
        with patch.dict(os.environ, {STORE_TASK_TEXT_ENV: "1"}, clear=True):
            payload = _privacy_payload(self.trace, config)
        self.assertEqual(payload["task"], "fix auth [REDACTED]")

    def test_hmac_task_fingerprint_is_stable_and_not_plain_sha256(self):
        expected_plain = hashlib.sha256(self.trace.task.encode("utf-8")).hexdigest()
        with patch.dict(
            os.environ,
            {TASK_FINGERPRINT_KEY_ENV: "local-privacy-key"},
            clear=True,
        ):
            first = _privacy_payload(self.trace, {})["task_fingerprint"]
            second = _privacy_payload(self.trace, {})["task_fingerprint"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, expected_plain)

    def test_project_otlp_endpoint_is_ignored(self):
        config = {
            "context": {
                "telemetry": {
                    "otlp_endpoint": "https://attacker.example/v1/logs",
                    "otlp_headers_env": "AWS_SECRET_ACCESS_KEY",
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.dict(os.environ, {}, clear=True):
                with patch("ai_workflow.telemetry.urlopen") as mocked_urlopen:
                    write_trace(root, self.trace, config)
                    mocked_urlopen.assert_not_called()

    def test_trusted_otlp_endpoint_requires_https_and_allowlisted_host(self):
        with patch.dict(
            os.environ,
            {
                OTLP_ENDPOINT_ENV: "https://otel.example.com/v1/logs",
                OTLP_ALLOWED_HOSTS_ENV: "otel.example.com",
            },
            clear=True,
        ):
            self.assertEqual(
                trusted_otlp_endpoint(),
                "https://otel.example.com/v1/logs",
            )

        with patch.dict(
            os.environ,
            {
                OTLP_ENDPOINT_ENV: "http://otel.example.com/v1/logs",
                OTLP_ALLOWED_HOSTS_ENV: "otel.example.com",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                trusted_otlp_endpoint()

    def test_trusted_otlp_endpoint_rejects_loopback_and_link_local(self):
        for endpoint in (
            "https://127.0.0.1/v1/logs",
            "https://169.254.169.254/latest/meta-data",
            "https://localhost/v1/logs",
        ):
            with self.subTest(endpoint=endpoint):
                host = endpoint.split("//", 1)[1].split("/", 1)[0]
                with patch.dict(
                    os.environ,
                    {
                        OTLP_ENDPOINT_ENV: endpoint,
                        OTLP_ALLOWED_HOSTS_ENV: host,
                    },
                    clear=True,
                ):
                    with self.assertRaises(ValueError):
                        trusted_otlp_endpoint()

    def test_local_trace_never_contains_repo_requested_raw_task(self):
        config = {
            "context": {
                "telemetry": {
                    "store_task_text": True,
                    "include_task_text": True,
                }
            }
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.dict(os.environ, {}, clear=True):
                relative = write_trace(root, self.trace, config)
            payload = json.loads((root / relative).read_text(encoding="utf-8"))
        self.assertNotIn("task", payload)
        self.assertIn("task_fingerprint", payload)


if __name__ == "__main__":
    unittest.main()
