from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class ProviderSemanticsTests(unittest.TestCase):
    def test_cacheable_provider_must_be_deterministic_and_side_effect_free(self):
        from ai_workflow.provenance import ProviderSemantics
        with self.assertRaises(ValueError):
            ProviderSemantics(cacheable=True, deterministic=False)
        with self.assertRaises(ValueError):
            ProviderSemantics(cacheable=True, deterministic=True, side_effecting=True)
        semantics = ProviderSemantics(deterministic=True, cacheable=True, idempotent=True, retryable=True, version="v1")
        self.assertTrue(semantics.cacheable)

    def test_cache_key_uses_policy_workspace_provider_and_canonical_request(self):
        from ai_workflow.retrieval_cache import cache_key
        from ai_workflow.provenance import ProviderSemantics
        semantics = ProviderSemantics(deterministic=True, cacheable=True, version="1.2")
        a = cache_key("policy-2", "workspace-abc", "semantic", semantics, {"b": 2, "a": 1})
        b = cache_key("policy-2", "workspace-abc", "semantic", semantics, {"a": 1, "b": 2})
        self.assertEqual(a, b)
        self.assertNotEqual(a, cache_key("policy-3", "workspace-abc", "semantic", semantics, {"a": 1, "b": 2}))

    def test_retrieval_cache_refuses_unstable_providers(self):
        from ai_workflow.retrieval_cache import RetrievalCache
        from ai_workflow.provenance import ProviderSemantics
        with tempfile.TemporaryDirectory() as td:
            cache = RetrievalCache(Path(td))
            unstable = ProviderSemantics(deterministic=False, cacheable=False, version="remote")
            self.assertFalse(cache.put("key", {"items": []}, unstable))
            self.assertIsNone(cache.get("key"))


class ProvenanceTests(unittest.TestCase):
    def test_run_metadata_separates_random_run_id_from_deterministic_identity(self):
        from ai_workflow.provenance import ArtifactReference, build_run_metadata
        kwargs = dict(
            workspace={"fingerprint": "workspace-fp", "git_head": "abc", "index_manifest_sha256": "idx"},
            config={"version": 2, "context": {"selector": {"enabled": True}}},
            retrieval_policy_version="policy-2",
            provider_versions={"semantic": "1.2"},
            changed_files=["b.py", "a.py"],
            artifacts=[ArtifactReference("dataset", "dvc://corpus@rev", digest="deadbeef", role="retrieval-corpus")],
            control_plane_version="2.3.0",
        )
        first = build_run_metadata(**kwargs); second = build_run_metadata(**kwargs)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(first.workspace_fingerprint, second.workspace_fingerprint)
        self.assertEqual(first.config_digest, second.config_digest)
        self.assertEqual(first.changed_files_digest, second.changed_files_digest)
        self.assertEqual(first.artifacts[0].uri, "dvc://corpus@rev")
        self.assertTrue(first.runtime["python"])
        self.assertTrue(first.runtime["platform"])

    def test_local_run_store_is_append_only_and_lineage_compatible(self):
        from ai_workflow.provenance import ArtifactReference, build_run_metadata, openlineage_event
        from ai_workflow.run_store import LocalJsonRunStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            metadata = build_run_metadata(
                workspace={"fingerprint": "fp"}, config={"version": 2}, retrieval_policy_version="p1",
                provider_versions={}, changed_files=[], artifacts=[ArtifactReference("model", "models:/retriever@prod", version="7", role="semantic-retriever")],
                control_plane_version="2.3.0",
            )
            rel = LocalJsonRunStore(root).add(metadata)
            path = root / rel; self.assertTrue(path.exists())
            stored = json.loads(path.read_text(encoding="utf-8")); self.assertEqual(stored["run_id"], metadata.run_id)
            event = openlineage_event(metadata, job_name="prepare-context")
            self.assertEqual(event["run"]["runId"], metadata.run_id)
            self.assertEqual(event["job"]["name"], "prepare-context")
            self.assertEqual(event["inputs"][0]["namespace"], "model")


class AdapterAndLibraryTests(unittest.IsolatedAsyncioTestCase):
    async def test_function_adapter_exposes_semantics_and_typed_result(self):
        from ai_workflow.models import ContextItem
        from ai_workflow.provenance import ProviderSemantics
        from ai_workflow.retrieval_adapters import FunctionRetrieverAdapter
        from ai_workflow.retrieval_contracts import RetrievalRequest
        adapter = FunctionRetrieverAdapter(
            "demo", lambda request: [ContextItem("demo", request.query, 1.0)],
            ProviderSemantics(deterministic=True, cacheable=True, version="1"),
        )
        result = await adapter.retrieve(RetrievalRequest("hello", Path.cwd(), 2))
        self.assertEqual(result.provider, "demo")
        self.assertEqual(result.items[0].text, "hello")
        self.assertTrue(adapter.semantics.cacheable)

    async def test_cached_adapter_only_caches_declared_stable_results(self):
        from ai_workflow.models import ContextItem
        from ai_workflow.provenance import ProviderSemantics
        from ai_workflow.retrieval_adapters import CachedRetrieverAdapter, FunctionRetrieverAdapter
        from ai_workflow.retrieval_cache import RetrievalCache
        from ai_workflow.retrieval_contracts import RetrievalRequest
        calls = {"n": 0}
        def provider(request):
            calls["n"] += 1
            return [ContextItem("demo", request.query, 1.0)]
        with tempfile.TemporaryDirectory() as td:
            semantics = ProviderSemantics(deterministic=True, cacheable=True, version="1")
            adapter = CachedRetrieverAdapter(FunctionRetrieverAdapter("demo", provider, semantics), RetrievalCache(Path(td)), "policy", "workspace")
            request = RetrievalRequest("hello", Path(td), 2)
            await adapter.retrieve(request); await adapter.retrieve(request)
            self.assertEqual(calls["n"], 1)

    def test_public_library_api_exports_engine_and_contracts(self):
        import ai_workflow
        self.assertTrue(hasattr(ai_workflow, "WorkflowEngine"))
        self.assertTrue(hasattr(ai_workflow, "RetrievalRequest"))
        self.assertTrue(hasattr(ai_workflow, "ProviderSemantics"))
        self.assertTrue(hasattr(ai_workflow, "ArtifactReference"))


if __name__ == "__main__": unittest.main()
