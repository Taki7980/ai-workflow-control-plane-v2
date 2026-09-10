from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class SetupSafetyTests(unittest.TestCase):
    def test_setup_requires_existing_root_unless_create_is_explicit(self):
        from ai_workflow.bootstrap import setup

        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing"
            with self.assertRaises(FileNotFoundError):
                setup(missing, "demo")
            result = setup(missing, "demo", create=True, index_mode="none")
            self.assertTrue(missing.is_dir())
            self.assertEqual(result["index"]["mode"], "skipped")

    def test_project_marker_is_repository_relative(self):
        from ai_workflow.bootstrap import setup

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup(root, "demo", index_mode="none")
            self.assertEqual((root / ".ai/PROJECT").read_text(encoding="utf-8"), ".\n")

    def test_setup_reuses_incremental_index_state(self):
        from ai_workflow.bootstrap import setup

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            first = setup(root, "demo")
            second = setup(root, "demo")
            self.assertEqual(first["index"]["mode"], "full")
            self.assertEqual(second["index"]["mode"], "incremental")


class CoreContractTests(unittest.TestCase):
    def test_context_dedupe_key_is_canonical_content_digest(self):
        from ai_workflow.models import ContextItem

        a = ContextItem("a", "alpha   beta\n gamma", 1.0)
        b = ContextItem("b", "alpha beta gamma", 1.0)
        self.assertEqual(a.dedupe_key, b.dedupe_key)
        self.assertNotIn("alpha", a.dedupe_key)
        self.assertGreaterEqual(len(a.dedupe_key), 32)

    def test_orchestration_contract_is_typed_but_json_compatible(self):
        from ai_workflow.config import default_config
        from ai_workflow.models import Lane, Risk, RouteDecision
        from ai_workflow.orchestration import OrchestrationContract, build_orchestration_contract
        from ai_workflow.providers import ProviderStatus

        self.assertTrue(hasattr(OrchestrationContract, "__required_keys__"))
        decision = RouteDecision(Lane.SMALL, Risk.LOW, ["test"], False, 0.9)
        providers = ProviderStatus(False, False, False, False, False)
        result = build_orchestration_contract(
            decision,
            {"retrieval_intent": "exact", "sufficiency": {"sufficient": True}},
            [],
            1,
            providers,
            default_config(),
        )
        self.assertIsInstance(result, dict)
        self.assertIn("agent_slots", result)

    def test_token_estimator_is_pluggable(self):
        from ai_workflow.config import estimate_tokens

        class Fixed:
            def estimate(self, text: str) -> int:
                return 7

        self.assertEqual(estimate_tokens("anything", estimator=Fixed()), 7)

    def test_selector_enforces_candidate_complexity_bound(self):
        from ai_workflow.context_selection import select_context
        from ai_workflow.models import ContextItem

        items = [ContextItem(f"s{i}", f"query evidence {i}", 1.0 - i / 100) for i in range(10)]
        selected, diagnostics = select_context(
            "query", items, budget_chars=10000, max_selector_candidates=3
        )
        self.assertLessEqual(diagnostics["selector_candidates"], 3)
        self.assertTrue(selected)

    def test_atomic_write_preserves_old_file_when_replace_fails(self):
        from ai_workflow.io_utils import atomic_write_text

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "state.txt"
            target.write_text("old", encoding="utf-8")
            with patch("ai_workflow.io_utils.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_doctor_has_versioned_machine_contract_and_capabilities(self):
        from ai_workflow.config import default_config
        from ai_workflow.doctor import run

        with tempfile.TemporaryDirectory() as td:
            result, _ = run(Path(td), default_config())
            self.assertEqual(result["schema_version"], 1)
            self.assertIn("core_ok", result)
            self.assertIn("optional_capabilities", result)

    def test_cli_exposes_setup_safety_and_hash_verification_flags(self):
        from ai_workflow.cli import build_parser

        setup_args = build_parser().parse_args(
            ["--root", "x", "setup", "--create", "--no-index"]
        )
        self.assertTrue(setup_args.create)
        self.assertTrue(setup_args.no_index)
        index_args = build_parser().parse_args(
            ["--root", "x", "index", "--incremental", "--verify-hashes"]
        )
        self.assertTrue(index_args.strict_hash)


if __name__ == "__main__":
    unittest.main()
