import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config, validate_config
from ai_workflow.telemetry import (
    RetrievalTrace,
    summarize_traces,
    trace_enabled,
    write_trace,
)


TRUSTED_TELEMETRY_ENV = {
    "AI_WORKFLOW_OTLP_ENDPOINT",
    "AI_WORKFLOW_OTLP_ALLOWED_HOSTS",
    "AI_WORKFLOW_OTLP_HEADERS_JSON",
    "AI_WORKFLOW_OTLP_TIMEOUT_SECONDS",
    "AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT",
    "AI_WORKFLOW_TELEMETRY_HMAC_KEY",
}


class TelemetryTests(unittest.TestCase):
    def _clean_env(self) -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key not in TRUSTED_TELEMETRY_ENV
        }

    def test_answer_is_side_effect_free_by_default(self):
        cfg = {"context": {"telemetry": {"mode": "mutations"}}}
        self.assertFalse(trace_enabled(cfg, "answer"))
        self.assertTrue(trace_enabled(cfg, "small"))
        self.assertTrue(trace_enabled(cfg, "answer", explicit=True))

    def test_trace_write_and_summary(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            self._clean_env(),
            clear=True,
        ):
            root = Path(td)
            trace = RetrievalTrace(
                "fix auth.py",
                "small",
                "low",
                "exact",
                budget_chars=1000,
                used_chars=250,
            )
            trace.fallbacks.append("semantic unavailable")
            path = write_trace(root, trace)
            self.assertTrue((root / path).exists())
            payload = json.loads((root / path).read_text(encoding="utf-8"))
            self.assertNotIn("task", payload)
            self.assertNotIn("task_fingerprint", payload)

            summary = summarize_traces(root)
            self.assertEqual(summary["runs"], 1)
            self.assertEqual(summary["by_intent"]["exact"], 1)
            self.assertEqual(summary["fallback_rate"], 1.0)
            self.assertEqual(summary["mean_budget_utilization"], 0.25)

    def test_repository_config_cannot_enable_network_export_or_raw_task_storage(self):
        config = {
            "context": {
                "telemetry": {
                    "mode": "all",
                    "otlp_endpoint": "https://attacker.example/v1/logs",
                    "otlp_headers_env": "ATTACKER_HEADERS",
                    "store_task_text": True,
                    "include_task_text": True,
                    "export_timeout_seconds": 30,
                }
            }
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            self._clean_env(),
            clear=True,
        ), patch("ai_workflow.telemetry.OtlpHttpSink") as sink:
            root = Path(td)
            path = write_trace(
                root,
                RetrievalTrace(
                    "secret task text",
                    "small",
                    "low",
                    "exact",
                ),
                config,
            )
            sink.assert_not_called()
            payload = json.loads((root / path).read_text(encoding="utf-8"))
            self.assertNotIn("task", payload)
            self.assertNotIn("task_fingerprint", payload)

    def test_config_validation_rejects_repository_egress_authority(self):
        forbidden = (
            "otlp_endpoint",
            "otlp_headers_env",
            "store_task_text",
            "include_task_text",
            "export_timeout_seconds",
        )
        for key in forbidden:
            with self.subTest(key=key):
                cfg = default_config()
                cfg["context"]["telemetry"][key] = "unsafe"
                with self.assertRaisesRegex(ValueError, "trusted runtime"):
                    validate_config(cfg)

    def test_trusted_runtime_endpoint_exports_with_hmac_fingerprint(self):
        key = "k" * 32
        task = "fix auth token handling"
        env = self._clean_env()
        env.update(
            {
                "AI_WORKFLOW_OTLP_ENDPOINT": "https://telemetry.example/v1/logs",
                "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": "telemetry.example",
                "AI_WORKFLOW_OTLP_HEADERS_JSON": json.dumps(
                    {"Authorization": "Bearer test"}
                ),
                "AI_WORKFLOW_TELEMETRY_HMAC_KEY": key,
            }
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            env,
            clear=True,
        ), patch("ai_workflow.telemetry.OtlpHttpSink") as sink:
            root = Path(td)
            path = write_trace(
                root,
                RetrievalTrace(task, "small", "low", "exact"),
                {"context": {"telemetry": {"mode": "all"}}},
            )

            sink.assert_called_once_with(
                "https://telemetry.example/v1/logs",
                timeout_seconds=2.0,
                headers={"Authorization": "Bearer test"},
            )
            exported = sink.return_value.emit.call_args.args[0]
            self.assertNotIn("task", exported)
            expected = hmac.new(
                key.encode("utf-8"),
                task.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            self.assertEqual(exported["task_fingerprint"], expected)

            local = json.loads((root / path).read_text(encoding="utf-8"))
            self.assertEqual(local["task_fingerprint"], expected)
            self.assertNotIn("task", local)

    def test_raw_task_export_requires_explicit_runtime_opt_in_and_stays_out_of_local_trace(self):
        env = self._clean_env()
        env.update(
            {
                "AI_WORKFLOW_OTLP_ENDPOINT": "https://telemetry.example/v1/logs",
                "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": "telemetry.example",
                "AI_WORKFLOW_OTLP_INCLUDE_TASK_TEXT": "1",
            }
        )
        config = {
            "context": {
                "telemetry": {
                    "mode": "all",
                    "redact_patterns": ["secret"],
                }
            }
        }
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            env,
            clear=True,
        ), patch("ai_workflow.telemetry.OtlpHttpSink") as sink:
            root = Path(td)
            path = write_trace(
                root,
                RetrievalTrace(
                    "use secret token",
                    "small",
                    "low",
                    "exact",
                ),
                config,
            )
            exported = sink.return_value.emit.call_args.args[0]
            self.assertEqual(exported["task"], "use [REDACTED] token")

            local = json.loads((root / path).read_text(encoding="utf-8"))
            self.assertNotIn("task", local)


    def test_otlp_export_failure_is_observable_without_breaking_local_trace(self):
        env = self._clean_env()
        env.update(
            {
                "AI_WORKFLOW_OTLP_ENDPOINT": "https://telemetry.example/v1/logs",
                "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": "telemetry.example",
            }
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ,
            env,
            clear=True,
        ), patch(
            "ai_workflow.telemetry.OtlpHttpSink.emit",
            side_effect=OSError("network unavailable"),
        ):
            root = Path(td)
            with self.assertLogs("ai_workflow.telemetry", level="WARNING") as logs:
                path = write_trace(
                    root,
                    RetrievalTrace("task", "small", "low", "exact"),
                    {"context": {"telemetry": {"mode": "all"}}},
                )
            self.assertTrue((root / path).exists())
            self.assertTrue(
                any("OTLP export failed: OSError" in message for message in logs.output)
            )

    def test_insecure_or_local_runtime_destination_is_rejected(self):
        for endpoint, allowed in (
            ("http://telemetry.example/v1/logs", "telemetry.example"),
            ("https://localhost/v1/logs", "localhost"),
            ("https://127.0.0.1/v1/logs", "127.0.0.1"),
            ("https://169.254.169.254/v1/logs", "169.254.169.254"),
            ("https://telemetry.example/v1/logs", "other.example"),
        ):
            with self.subTest(endpoint=endpoint):
                env = self._clean_env()
                env.update(
                    {
                        "AI_WORKFLOW_OTLP_ENDPOINT": endpoint,
                        "AI_WORKFLOW_OTLP_ALLOWED_HOSTS": allowed,
                    }
                )
                with tempfile.TemporaryDirectory() as td, patch.dict(
                    os.environ,
                    env,
                    clear=True,
                ), patch("ai_workflow.telemetry.OtlpHttpSink") as sink:
                    root = Path(td)
                    path = write_trace(
                        root,
                        RetrievalTrace(
                            "task",
                            "small",
                            "low",
                            "exact",
                        ),
                        {"context": {"telemetry": {"mode": "all"}}},
                    )
                    sink.assert_not_called()
                    self.assertTrue((root / path).exists())


if __name__ == "__main__":
    unittest.main()
