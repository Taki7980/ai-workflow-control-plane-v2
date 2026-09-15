import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from ai_workflow.context_broker import _domain_hints, _score, lightweight

class ContextBrokerTests(unittest.TestCase):
    def test_lightweight_can_exclude_project_knowledge_without_memory_migration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "ai-workspace" / "memory" / "memory.jsonl"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(
                '{"id":"mem-1","type":"pattern","created_at":"2026-01-01T00:00:00+00:00","verified_at":"2026-01-01T00:00:00+00:00","keywords":["bm25"],"summary":"prior project knowledge","evidence":"","files":[],"source_hashes":{},"confidence":1.0}\n',
                encoding="utf-8",
            )
            with patch(
                "ai_workflow.context_broker.load_state",
                return_value={},
            ), patch(
                "ai_workflow.context_broker._jsonl",
                side_effect=[[], []],
            ), patch(
                "ai_workflow.context_broker.search_memory",
            ) as memory_search:
                items = lightweight(
                    root,
                    "bm25",
                    None,
                    None,
                    limit=5,
                    min_conf=0.5,
                    include_project_knowledge=False,
                )

            self.assertEqual(items, [])
            memory_search.assert_not_called()
            self.assertFalse(
                (root / "ai-workspace" / "memory" / "memory.sqlite3").exists()
            )

    def test_score_uses_tokens_not_substrings(self):
        self.assertEqual(_score("auth", "author guide"), 0)
        self.assertEqual(_score("ProcessPayment", "def ProcessPayment():"), 3)

    def test_domain_manifest_routes_matching_module(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root/'ai-workspace/agents/domain-manifest.yaml'
            p.parent.mkdir(parents=True)
            p.write_text('''backend:\n  auth:\n    keywords: ["login", "token"]\n    paths: ["backend/auth/"]\nfrontend:\n''')
            rows = _domain_hints(root, 'fix login token handling', 5)
            self.assertEqual(rows[0].source, 'domain_manifest')
            self.assertIn('backend/auth', rows[0].text)

    def test_domain_manifest_multiline_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root/'ai-workspace/agents/domain-manifest.yaml'
            p.parent.mkdir(parents=True)
            p.write_text('''services:\n  billing:\n    keywords:\n      - invoice\n      - stripe\n    paths:\n      - services/billing/\n''')
            rows = _domain_hints(root, 'fix stripe invoice error', 5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].source, 'domain_manifest')
            self.assertIn('services/billing', rows[0].text)

    def test_lightweight_keeps_crg_signal_over_stopword_heavy_symbol_noise(self):
        rows = [
            {"symbol": "test_registry_mutation_waits_for_interprocess_lock", "file": "tests/test_repository_registry.py"},
            {"symbol": "test_superpowers_can_be_forced_for_marketplace_installs", "file": "tests/test_providers.py"},
            {"symbol": "_spec_for_directory", "file": "ai_workflow/repository_registry.py"},
            {"symbol": "test_spring_mapping_routes_do_not_depend_on_generic_capture_groups", "file": "tests/test_indexer_routes_and_state.py"},
            {"symbol": "test_per_query_floor_cannot_be_hidden_by_overall_mean", "file": "tests/test_benchmark_regression_policy.py"},
            {"symbol": "test_sample_corpus_is_broad_enough_for_regression_use", "file": "tests/test_benchmark_dataset.py"},
            {"symbol": "test_task_text_can_be_enabled_and_redacted", "file": "tests/test_durable_state.py"},
            {"symbol": "test_failed_crg_status_is_not_reported_ready", "file": "tests/test_doctor.py"},
        ]
        with tempfile.TemporaryDirectory() as td, patch(
            "ai_workflow.context_broker.load_state", return_value={}
        ), patch(
            "ai_workflow.context_broker._jsonl", side_effect=[rows, []]
        ), patch(
            "ai_workflow.context_broker.row_fresh", return_value=True
        ), patch(
            "ai_workflow.context_broker._domain_hints", return_value=[]
        ), patch(
            "ai_workflow.context_broker._research_hits", return_value=[]
        ), patch(
            "ai_workflow.context_broker.search_memory", return_value=[]
        ):
            items = lightweight(
                Path(td),
                "Where do we decide whether CRG should be attempted for a large repository?",
                None,
                None,
                limit=6,
                min_conf=0.5,
            )

        self.assertEqual(len(items), 6)
        self.assertTrue(any('"symbol":"test_failed_crg_status_is_not_reported_ready"' in item.text for item in items))

from ai_workflow.context_broker import gather
from ai_workflow.budget import budget_for
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
import json

class StructuralFallbackTests(unittest.TestCase):
    def test_targeted_source_is_lazy_when_lightweight_evidence_is_sufficient(self):
        cfg = json.loads(
            (Path(__file__).parents[1] / "ai-workspace/config/control-plane.json").read_text()
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decision = RouteDecision(Lane.SMALL, Risk.LOW, ["bounded"], False)
            evidence = [ContextItem("lightweight_index", "payment handler", 1.0)]
            with patch("ai_workflow.context_broker.hot_cache", return_value=[]), patch(
                "ai_workflow.context_broker.lightweight",
                return_value=evidence,
            ), patch("ai_workflow.context_broker.targeted_source") as fallback:
                items = gather(
                    root,
                    "update payment handler",
                    decision,
                    budget_for(Lane.SMALL, cfg),
                    cfg,
                    ProviderStatus(False, False, False, False),
                )

            self.assertTrue(items)
            fallback.assert_not_called()

    def test_crg_only_queries_requested_relationship(self):
        import ai_workflow.context_broker as cb

        calls = []

        def fake_run(root, args, timeout=8):
            calls.append(args)
            return {
                "status": "ok",
                "pattern": "callers_of",
                "target": "TargetFunc",
                "result_count": 1,
                "results": [
                    {
                        "name": "Caller",
                        "qualified_name": "service.py::Caller",
                        "file_path": "service.py",
                    }
                ],
                "edges": [{"kind": "CALLS"}],
            }

        with tempfile.TemporaryDirectory() as td, patch.object(
            cb, "_run_crg", side_effect=fake_run
        ):
            items = cb.crg_context(
                Path(td),
                "Who calls TargetFunc?",
                "TargetFunc",
                None,
                5,
            )

        self.assertEqual(calls, [["query", "callers_of", "TargetFunc"]])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "code_review_graph")
        self.assertEqual(items[0].metadata["pattern"], "callers_of")
        self.assertTrue(items[0].metadata["structural_valid"])
        self.assertEqual(items[0].metadata["result_count"], 1)

    def test_structural_query_falls_back_to_source_without_crg(self):
        cfg = json.loads((Path(__file__).parents[1]/'ai-workspace/config/control-plane.json').read_text())
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'service.py').write_text('def ProcessPayment():\n    return True\n')
            (root/'ai-workspace/generated').mkdir(parents=True)
            decision=RouteDecision(Lane.FULL,Risk.MEDIUM,['structural'],True)
            items=gather(root,'blast radius ProcessPayment',decision,budget_for(Lane.FULL,cfg),cfg,ProviderStatus(False,False,False,False),symbol='ProcessPayment')
            self.assertTrue(any(i.source == 'targeted_source' for i in items))

class StructuralCRGContractTests(unittest.TestCase):
    def test_blast_radius_uses_impact_evidence(self):
        import ai_workflow.context_broker as cb

        calls = []

        def fake_run(root, args, timeout=8):
            calls.append(args)
            return {
                "status": "ok",
                "summary": "1 impacted node",
                "total_impacted": 1,
                "impacted_nodes": [
                    {
                        "name": "CheckoutService",
                        "file_path": "checkout.py",
                    }
                ],
                "impacted_files": ["checkout.py"],
                "edges": [{"kind": "CALLS"}],
                "truncated": False,
            }

        with tempfile.TemporaryDirectory() as td, patch.object(
            cb, "_run_crg", side_effect=fake_run
        ):
            items = cb.crg_context(
                Path(td),
                "What is the blast radius of this change?",
                None,
                ["service.py"],
                5,
            )

        self.assertEqual(calls, [["impact", "--files", "service.py"]])
        self.assertEqual(items[0].metadata["pattern"], "impact")
        self.assertTrue(items[0].metadata["structural_valid"])

    def test_crg_search_result_becomes_anchor_before_relationship_query(self):
        import ai_workflow.context_broker as cb

        calls = []

        def fake_run(root, args, timeout=8):
            calls.append(args)
            if args[0] == "search":
                return {
                    "status": "ok",
                    "query": "Who calls the payment retry handler?",
                    "results": [
                        {
                            "name": "ProcessPayment",
                            "qualified_name": "billing.py::ProcessPayment",
                            "file_path": "billing.py",
                            "score": 0.92,
                        }
                    ],
                }
            return {
                "status": "ok",
                "pattern": "callers_of",
                "target": "billing.py::ProcessPayment",
                "result_count": 1,
                "results": [
                    {
                        "name": "CheckoutService",
                        "qualified_name": "checkout.py::CheckoutService",
                        "file_path": "checkout.py",
                    }
                ],
                "edges": [{"kind": "CALLS"}],
            }

        with tempfile.TemporaryDirectory() as td, patch.object(
            cb, "_run_crg", side_effect=fake_run
        ):
            items = cb.crg_context(
                Path(td),
                "Who calls the payment retry handler?",
                None,
                None,
                5,
            )

        self.assertEqual(calls[0][0], "search")
        self.assertEqual(
            calls[1],
            ["query", "callers_of", "billing.py::ProcessPayment"],
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metadata["pattern"], "callers_of")
        self.assertEqual(
            items[0].metadata["anchor"],
            "billing.py::ProcessPayment",
        )

    def test_verified_empty_relation_is_retained_as_structural_evidence(self):
        import ai_workflow.context_broker as cb

        payload = {
            "status": "ok",
            "pattern": "callers_of",
            "target": "TargetFunc",
            "result_count": 0,
            "results": [],
            "edges": [],
            "confidence": (
                "'TargetFunc' is indexed and the graph is current, "
                "so this 0 is a real absence"
            ),
        }
        with tempfile.TemporaryDirectory() as td, patch.object(
            cb, "_run_crg", return_value=payload
        ):
            items = cb.crg_context(
                Path(td),
                "Who calls TargetFunc?",
                "TargetFunc",
                None,
                5,
            )

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].metadata["empty_verified"])
        self.assertTrue(items[0].metadata["structural_valid"])

    def test_unverified_empty_relation_does_not_claim_structural_completion(self):
        import ai_workflow.context_broker as cb

        payload = {
            "status": "ok",
            "pattern": "callers_of",
            "target": "TargetFunc",
            "result_count": 0,
            "results": [],
            "edges": [],
            "confidence": (
                "'TargetFunc' is indexed and no such edge is recorded; "
                "graph currency unverified"
            ),
        }
        with tempfile.TemporaryDirectory() as td, patch.object(
            cb, "_run_crg", return_value=payload
        ):
            items = cb.crg_context(
                Path(td),
                "Who calls TargetFunc?",
                "TargetFunc",
                None,
                5,
            )

        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].metadata["empty_verified"])
        self.assertFalse(items[0].metadata["structural_valid"])

    def test_run_crg_rejects_malformed_json(self):
        from types import SimpleNamespace
        import ai_workflow.context_broker as cb

        proc = SimpleNamespace(
            returncode=0,
            stdout="{not-json",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as td, patch.object(
            cb.shutil, "which", return_value="code-review-graph"
        ), patch.object(
            cb, "graph_exists", return_value=True
        ), patch.object(
            cb.subprocess, "run", return_value=proc
        ):
            result = cb._run_crg(Path(td), ["search", "query"])

        self.assertIsNone(result)
