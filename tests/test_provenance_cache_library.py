from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path


class ExecutionSemanticsTests(unittest.TestCase):
    def test_cache_requires_explicit_deterministic_cacheable_non_side_effecting_semantics(self):
        from ai_workflow.execution_semantics import ProviderSemantics, cache_eligible

        self.assertFalse(cache_eligible(ProviderSemantics()))
        self.assertTrue(cache_eligible(ProviderSemantics(deterministic=True, cacheable=True)))
        self.assertFalse(cache_eligible(ProviderSemantics(deterministic=True, cacheable=True, side_effecting=True)))

    def test_command_provider_parses_version_and_semantics_safely(self):
        from ai_workflow.provider_runner import command_provider_spec

        default = command_provider_spec({"name": "x", "command": ["tool"]})
        self.assertEqual(default.version, "unknown")
        self.assertFalse(default.semantics.cacheable)
        explicit = command_provider_spec({
            "name": "x",
            "command": ["tool"],
            "version": "2026.09",
            "semantics": {"deterministic": True, "cacheable": True, "idempotent": True, "retryable": True},
        })
        self.assertEqual(explicit.version, "2026.09")
        self.assertTrue(explicit.semantics.deterministic)
        self.assertTrue(explicit.semantics.cacheable)


class RetrievalCacheTests(unittest.TestCase):
    def test_cache_key_is_canonical_and_version_sensitive(self):
        from ai_workflow.retrieval_cache import retrieval_cache_key
        from ai_workflow.retrieval_contracts import RetrievalRequest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = RetrievalRequest("query", root, 5, intent="exact", changed_files=("a.py",), metadata={"z": 2, "a": 1})
            b = RetrievalRequest("query", root, 5, intent="exact", changed_files=("a.py",), metadata={"a": 1, "z": 2})
            key_a = retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v1", a)
            key_b = retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v1", b)
            self.assertEqual(key_a, key_b)
            self.assertNotEqual(key_a, retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v2", a))
            self.assertNotIn(str(root), key_a)

    def test_file_cache_refuses_ineligible_provider_and_round_trips_eligible_result(self):
        from ai_workflow.execution_semantics import ProviderSemantics
        from ai_workflow.models import ContextItem
        from ai_workflow.retrieval_cache import FileRetrievalCache
        from ai_workflow.retrieval_contracts import ProviderResult

        with tempfile.TemporaryDirectory() as td:
            cache = FileRetrievalCache(Path(td))
            result = ProviderResult("p", (ContextItem("p", "evidence", 1.0),), 1.0)
            self.assertFalse(cache.put("k", result, ProviderSemantics()))
            self.assertIsNone(cache.get("k"))
            semantics = ProviderSemantics(deterministic=True, cacheable=True)
            self.assertTrue(cache.put("k", result, semantics))
            loaded = cache.get("k")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.provider, "p")
            self.assertEqual(loaded.items[0].text, "evidence")


class ProvenanceTests(unittest.TestCase):
    def test_run_id_is_random_but_reproducibility_inputs_are_stable(self):
        from ai_workflow.provenance import ArtifactReference, RunMetadata

        kwargs = dict(
            control_plane_version="2.3.0",
            workspace_fingerprint="workspace",
            git_head="abc",
            changed_files_digest="changed",
            config_digest="config",
            retrieval_policy_version="policy-v1",
            index_manifest_digest="index",
            provider_versions={"semantic": "1"},
            artifacts=(ArtifactReference("model", "models:/retriever@prod", version="1", role="semantic-retriever"),),
        )
        a = RunMetadata.create(**kwargs)
        b = RunMetadata.create(**kwargs)
        self.assertNotEqual(a.run_id, b.run_id)
        self.assertEqual(a.reproducibility_key(), b.reproducibility_key())
        self.assertIn("python", a.runtime)
        self.assertIn("platform", a.runtime)

    def test_local_run_store_is_immutable_and_openlineage_mapping_is_explicit(self):
        from ai_workflow.provenance import ArtifactReference, LocalRunStore, RunMetadata, to_openlineage

        with tempfile.TemporaryDirectory() as td:
            run = RunMetadata.create(
                control_plane_version="2.3.0", workspace_fingerprint="fp", git_head=None,
                changed_files_digest="c", config_digest="cfg", retrieval_policy_version="p",
                index_manifest_digest="idx", provider_versions={},
                artifacts=(ArtifactReference("dataset", "dvc://corpus@rev", digest="deadbeef", role="retrieval-corpus"),),
            )
            store = LocalRunStore(Path(td))
            store.add(run)
            self.assertEqual(store.get(run.run_id).run_id, run.run_id)
            with self.assertRaises(FileExistsError):
                store.add(run)
            event = to_openlineage(run, job_name="ai-workflow.prepare")
            self.assertEqual(event["run"]["runId"], run.run_id)
            self.assertEqual(event["job"]["name"], "ai-workflow.prepare")
            self.assertEqual(event["inputs"][0]["namespace"], "dataset")


class AdapterAndLibraryTests(unittest.TestCase):
    def test_sync_retriever_adapter_exposes_async_protocol_without_changing_result(self):
        from ai_workflow.models import ContextItem
        from ai_workflow.retrieval_adapters import SyncRetrieverAdapter
        from ai_workflow.retrieval_contracts import ProviderResult, RetrievalRequest

        class Legacy:
            name = "legacy"
            def retrieve(self, request):
                return ProviderResult(self.name, (ContextItem("legacy", request.query, 1.0),), 2.0)

        async def exercise():
            with tempfile.TemporaryDirectory() as td:
                adapter = SyncRetrieverAdapter(Legacy())
                result = await adapter.retrieve(RetrievalRequest("hello", Path(td), 1))
                return adapter.name, result

        name, result = asyncio.run(exercise())
        self.assertEqual(name, "legacy")
        self.assertEqual(result.items[0].text, "hello")

    def test_public_library_prepare_is_cli_independent_and_typed(self):
        from ai_workflow.api import TaskRequest, WorkflowClient, WorkflowResult
        from ai_workflow.models import ContextItem

        class Engine:
            async def gather_detailed_async(self, root, query, decision, budget, config, providers, *args, **kwargs):
                return [ContextItem("test", "context", 1.0)], {
                    "retrieval_intent": "exact",
                    "evidence_state": "sufficient",
                    "orchestration": {"agent_slots": 1},
                    "workspace_state": {"fingerprint": "fp"},
                }

        async def exercise():
            with tempfile.TemporaryDirectory() as td:
                return await WorkflowClient(engine=Engine()).prepare(TaskRequest("explain this", Path(td)))

        result = asyncio.run(exercise())
        self.assertIsInstance(result, WorkflowResult)
        self.assertEqual(result.task.text, "explain this")
        self.assertEqual(result.context[0].text, "context")
        self.assertEqual(result.retrieval["evidence_state"], "sufficient")


if __name__ == "__main__":
    unittest.main()
