import json
import math
import tempfile
import unittest
from pathlib import Path

from ai_workflow.execution_semantics import ProviderSemantics
from ai_workflow.provider_runner import CommandProviderSpec, _result_from_bytes
from ai_workflow.retrieval_cache import FileRetrievalCache
from ai_workflow.retrieval_contracts import RetrievalRequest


class ProviderProtocolHardeningTests(unittest.TestCase):
    def _result(self, payload: object):
        request = RetrievalRequest("query", Path("."), 8)
        spec = CommandProviderSpec("test", ("provider",))
        if isinstance(payload, bytes):
            raw = payload
        elif isinstance(payload, str):
            raw = payload.encode("utf-8")
        else:
            raw = json.dumps(payload, allow_nan=True).encode("utf-8")
        return _result_from_bytes(
            spec,
            request,
            "external:test",
            None,
            raw,
            1.0,
            0,
        )

    def test_non_rfc_json_constants_are_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                result = self._result(
                    f'{{"items":[{{"text":"x","score":{token}}}]}}'
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, "invalid_payload")
                self.assertEqual(result.items, ())

    def test_numeric_overflow_and_out_of_range_scores_are_rejected(self):
        for raw in (
            '{"items":[{"text":"x","score":1e9999}]}',
            '{"items":[{"text":"x","score":-0.01}]}',
            '{"items":[{"text":"x","score":1.01}]}',
        ):
            with self.subTest(raw=raw):
                result = self._result(raw)
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, "invalid_payload")
                self.assertEqual(result.items, ())

    def test_duplicate_json_keys_are_rejected(self):
        result = self._result(
            '{"items":[{"text":"first","text":"second","score":0.5}]}'
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "invalid_payload")
        self.assertEqual(result.items, ())

    def test_schema_rejects_wrong_types_and_line_bounds(self):
        cases = [
            {"items": [{"text": {"nested": "object"}, "score": 0.5}]},
            {"items": [{"text": "x", "score": "0.5"}]},
            {"items": [{"text": "x", "score": True}]},
            {"items": [{"text": "x", "score": 0.5, "stale": "false"}]},
            {"items": [{"text": "x", "score": 0.5, "metadata": []}]},
            {"items": [{"text": "x", "score": 0.5, "provenance": []}]},
            {"items": [{"text": "x", "score": 0.5, "line": 0}]},
            {"items": [{"text": "x", "score": 0.5, "line": 2**40}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                result = self._result(payload)
                self.assertFalse(result.ok)
                self.assertEqual(result.error_kind, "invalid_payload")
                self.assertEqual(result.items, ())

    def test_protocol_bounds_reject_too_many_items_and_deep_metadata(self):
        too_many = {
            "items": [
                {"text": f"item-{index}", "score": 0.5}
                for index in range(1025)
            ]
        }
        result = self._result(too_many)
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "invalid_payload")

        nested: object = "leaf"
        for _ in range(12):
            nested = {"next": nested}
        result = self._result(
            {"items": [{"text": "x", "score": 0.5, "metadata": nested}]}
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "invalid_payload")

    def test_valid_boundary_payload_remains_usable(self):
        result = self._result(
            {
                "items": [
                    {
                        "text": "bounded evidence",
                        "score": 1.0,
                        "stale": False,
                        "line": 1,
                        "end_line": 2,
                        "metadata": {"symbol": "ProcessPayment"},
                        "provenance": {"provider_revision": "v1"},
                    }
                ]
            }
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].score, 1.0)
        self.assertFalse(result.items[0].stale)

    def test_rejected_payload_cannot_enter_cache(self):
        result = self._result(
            '{"items":[{"text":"poison","score":NaN}]}'
        )
        self.assertFalse(result.ok)
        with tempfile.TemporaryDirectory() as td:
            cache = FileRetrievalCache(Path(td))
            written = cache.put(
                "invalid-provider-result",
                result,
                ProviderSemantics(
                    deterministic=True,
                    cacheable=True,
                    side_effecting=False,
                ),
            )
            self.assertFalse(written)
            self.assertIsNone(cache.get("invalid-provider-result"))

    def test_rejected_score_never_becomes_rankable_context(self):
        result = self._result(
            '{"items":[{"text":"rank poison","score":1e9999}]}'
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.items, ())
        self.assertFalse(
            any(
                math.isfinite(item.score)
                for item in result.items
            )
        )


if __name__ == "__main__":
    unittest.main()
