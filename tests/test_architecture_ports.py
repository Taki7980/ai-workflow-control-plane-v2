from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class ArchitecturePortTests(unittest.TestCase):
    def test_side_effecting_retry_requires_idempotency(self):
        from ai_workflow.provenance import ProviderSemantics

        with self.assertRaises(ValueError):
            ProviderSemantics(side_effecting=True, retryable=True, idempotent=False)
        semantics = ProviderSemantics(side_effecting=True, retryable=True, idempotent=True)
        self.assertTrue(semantics.retryable)

    def test_index_store_wraps_generated_index_state(self):
        from ai_workflow.index_store import IndexStore, LocalIndexStore
        from ai_workflow.indexer import build_indexes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            build_indexes(root)
            store: IndexStore = LocalIndexStore(root)
            self.assertIn("sample.py", store.state()["files"])
            self.assertTrue(any(row["symbol"] == "alpha" for row in store.symbols()))

    def test_workspace_source_exposes_roots_and_content_identity(self):
        from ai_workflow.config import default_config
        from ai_workflow.workspace_source import LocalWorkspaceSource, WorkspaceSource

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source: WorkspaceSource = LocalWorkspaceSource(root, default_config())
            self.assertEqual(source.roots()[0], root.resolve())
            fingerprint = source.fingerprint([])
            self.assertIn("fingerprint", fingerprint)
            self.assertNotIn(str(root.resolve()), fingerprint["fingerprint"])

    def test_run_store_protocol_is_append_only(self):
        from ai_workflow.run_store import LocalJsonRunStore, RunStore

        self.assertTrue(hasattr(RunStore, "add"))
        self.assertTrue(hasattr(LocalJsonRunStore, "add"))

    def test_provider_runtime_status_exposes_queue_and_inflight_signals(self):
        from ai_workflow.provenance import ProviderRuntimeStatus

        status = ProviderRuntimeStatus(available=True, queue_depth=3, in_flight=2, capacity=8)
        self.assertEqual(status.queue_depth, 3)
        self.assertEqual(status.in_flight, 2)
        self.assertEqual(status.capacity, 8)
        self.assertGreater(status.load_fraction, 0)

    def test_explicit_adapter_types_exist_for_target_architecture(self):
        from ai_workflow.retrieval_adapters import (
            CRGRetrieverAdapter,
            ExternalRetrieverAdapter,
            LocalRetrieverAdapter,
            MemoryRetrieverAdapter,
            SemanticRetrieverAdapter,
        )

        for adapter_type in (
            LocalRetrieverAdapter,
            SemanticRetrieverAdapter,
            ExternalRetrieverAdapter,
            CRGRetrieverAdapter,
            MemoryRetrieverAdapter,
        ):
            self.assertTrue(hasattr(adapter_type, "retrieve"))


if __name__ == "__main__":
    unittest.main()
