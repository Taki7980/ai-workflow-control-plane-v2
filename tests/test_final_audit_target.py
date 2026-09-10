from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ProviderSemanticsAndResourceTests(unittest.TestCase):
    def test_provider_semantics_are_fail_closed_and_versioned(self):
        from ai_workflow.execution_semantics import ProviderSemantics, cache_eligible
        from ai_workflow.provider_runner import command_provider_spec

        default = command_provider_spec({"name": "x", "command": ["tool"]})
        self.assertEqual(default.version, "unknown")
        self.assertFalse(cache_eligible(default.semantics))

        explicit = command_provider_spec(
            {
                "name": "x",
                "command": ["tool"],
                "version": "2026.09",
                "semantics": {
                    "deterministic": True,
                    "cacheable": True,
                    "side_effecting": False,
                },
            }
        )
        self.assertEqual(explicit.version, "2026.09")
        self.assertTrue(cache_eligible(explicit.semantics))
        self.assertFalse(cache_eligible(ProviderSemantics(deterministic=True, cacheable=True, side_effecting=True)))

    def test_sync_provider_closes_both_pipes(self):
        from ai_workflow.provider_runner import CommandProviderSpec, run_command_provider
        from ai_workflow.retrieval_contracts import RetrievalRequest

        class FakeProcess:
            def __init__(self) -> None:
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(b'[{"text":"evidence","score":1.0}]')
                self.returncode = 0

            def wait(self, timeout=None):
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

        process = FakeProcess()
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.provider_runner.subprocess.Popen", return_value=process
        ):
            result = run_command_provider(
                CommandProviderSpec("test", ("unused",)),
                RetrievalRequest("evidence", Path(td), 1),
                source="test",
            )

        self.assertTrue(result.ok)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)


class ProvenanceAndCacheTests(unittest.TestCase):
    def test_run_identity_is_random_but_reproducibility_key_is_stable(self):
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
            artifacts=(
                ArtifactReference(
                    "model",
                    "models:/retriever@prod",
                    version="1",
                    role="semantic-retriever",
                ),
            ),
        )
        first = RunMetadata.create(**kwargs)
        second = RunMetadata.create(**kwargs)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual(first.reproducibility_key(), second.reproducibility_key())
        self.assertNotIn("task", first.to_dict())
        self.assertIn("python", first.runtime)
        self.assertIn("platform", first.runtime)

    def test_retrieval_cache_is_canonical_versioned_and_never_caches_failures(self):
        from ai_workflow.execution_semantics import ProviderSemantics
        from ai_workflow.models import ContextItem
        from ai_workflow.retrieval_cache import FileRetrievalCache, retrieval_cache_key
        from ai_workflow.retrieval_contracts import ProviderResult, RetrievalRequest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = RetrievalRequest(
                "query",
                root,
                5,
                intent="exact",
                changed_files=("a.py",),
                metadata={"z": 2, "a": 1},
            )
            second = RetrievalRequest(
                "query",
                root,
                5,
                intent="exact",
                changed_files=("a.py",),
                metadata={"a": 1, "z": 2},
            )
            key_a = retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v1", first)
            key_b = retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v1", second)
            self.assertEqual(key_a, key_b)
            self.assertNotEqual(
                key_a,
                retrieval_cache_key("policy-v1", "workspace-fp", "semantic", "v2", first),
            )
            self.assertNotIn(str(root), key_a)

            cache = FileRetrievalCache(root / "cache")
            semantics = ProviderSemantics(deterministic=True, cacheable=True)
            good = ProviderResult("p", (ContextItem("p", "evidence", 1.0),), 1.0)
            bad = ProviderResult("p", error="failed", error_kind="exit")
            self.assertTrue(cache.put("good", good, semantics))
            self.assertFalse(cache.put("bad", bad, semantics))
            self.assertIsNone(cache.get("bad"))
            self.assertEqual(cache.get("good").items[0].text, "evidence")

    def test_local_run_store_is_immutable_and_openlineage_mapping_is_explicit(self):
        from ai_workflow.provenance import ArtifactReference, LocalRunStore, RunMetadata, to_openlineage

        with tempfile.TemporaryDirectory() as td:
            run = RunMetadata.create(
                control_plane_version="2.3.0",
                workspace_fingerprint="fp",
                git_head=None,
                changed_files_digest="c",
                config_digest="cfg",
                retrieval_policy_version="p",
                index_manifest_digest="idx",
                provider_versions={},
                artifacts=(
                    ArtifactReference(
                        "dataset",
                        "dvc://corpus@rev",
                        digest="deadbeef",
                        role="input:retrieval-corpus",
                    ),
                ),
            )
            store = LocalRunStore(Path(td))
            store.add(run)
            loaded = store.get(run.run_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.run_id, run.run_id)
            with self.assertRaises(FileExistsError):
                store.add(run)
            event = to_openlineage(run, job_name="ai-workflow.prepare")
            self.assertEqual(event["run"]["runId"], run.run_id)
            self.assertEqual(event["job"]["name"], "ai-workflow.prepare")
            self.assertEqual(event["inputs"][0]["namespace"], "dataset")


class PublicLibraryApiTests(unittest.TestCase):
    def test_public_prepare_is_typed_cli_independent_and_side_effect_free_by_default(self):
        from ai_workflow import TaskRequest, WorkflowClient, WorkflowResult, __version__
        from ai_workflow.models import ContextItem

        class Engine:
            async def gather_detailed_async(self, root, query, decision, budget, config, providers, *args, **kwargs):
                self.write_telemetry = kwargs.get("write_telemetry")
                return [ContextItem("test", "context", 1.0)], {
                    "retrieval_intent": "exact",
                    "evidence_state": "sufficient",
                    "workspace_state": {"fingerprint": "fp"},
                    "orchestration": {"agent_slots": 1},
                }

        async def exercise(root: Path):
            engine = Engine()
            result = await WorkflowClient(engine=engine).prepare(TaskRequest("explain this", root))
            return result, engine.write_telemetry

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result, write_telemetry = asyncio.run(exercise(root))
            self.assertIsInstance(result, WorkflowResult)
            self.assertEqual(result.task.text, "explain this")
            self.assertEqual(result.context[0].text, "context")
            self.assertEqual(result.run.control_plane_version, __version__)
            self.assertFalse(write_telemetry)
            self.assertFalse((root / "ai-workspace" / "runs").exists())

    def test_sync_retriever_adapter_preserves_result_contract(self):
        from ai_workflow.models import ContextItem
        from ai_workflow.retrieval_adapters import SyncRetrieverAdapter
        from ai_workflow.retrieval_contracts import ProviderResult, RetrievalRequest

        class Legacy:
            name = "legacy"

            def retrieve(self, request):
                return ProviderResult(
                    self.name,
                    (ContextItem("legacy", request.query, 1.0),),
                    2.0,
                )

        async def exercise():
            with tempfile.TemporaryDirectory() as td:
                adapter = SyncRetrieverAdapter(Legacy())
                return await adapter.retrieve(RetrievalRequest("hello", Path(td), 1))

        result = asyncio.run(exercise())
        self.assertEqual(result.provider, "legacy")
        self.assertEqual(result.items[0].text, "hello")


class GovernanceClosureTests(unittest.TestCase):
    def test_final_governance_and_audit_documents_exist_without_placeholders(self):
        root = Path(__file__).resolve().parents[1]
        required = (
            "SECURITY.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "docs/reproducibility.md",
            "docs/audit-compliance.md",
        )
        for relative in required:
            path = root / relative
            self.assertTrue(path.is_file(), relative)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("TBD", text)
            self.assertNotIn("TODO", text)

        matrix = (root / "docs" / "audit-compliance.md").read_text(encoding="utf-8")
        for priority in ("P0", "P1", "P2", "P3"):
            self.assertIn(priority, matrix)
        self.assertIn("profil", matrix.lower())
        self.assertIn("daemon", matrix.lower())


if __name__ == "__main__":
    unittest.main()
