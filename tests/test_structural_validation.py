import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.models import ContextItem
from ai_workflow.structural_validation import (
    StructuralEvidenceConfidence,
    validate_crg_item,
)


def crg_item(path: str = "src/service.py", name: str = "charge") -> ContextItem:
    return ContextItem(
        "code_review_graph",
        json.dumps(
            {
                "status": "ok",
                "pattern": "callers_of",
                "results": [{"path": path, "name": name}],
            }
        ),
        9.0,
        False,
        {"pattern": "callers_of", "anchor": "charge", "result_count": 1},
    )


class StructuralValidationTests(unittest.TestCase):
    def test_crg_only_result_remains_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            item = validate_crg_item(
                root,
                crg_item(),
                query="who calls charge",
                symbol="charge",
                changed_files=[],
                limit=10,
            )
        self.assertEqual(
            item.metadata["evidence_confidence"],
            StructuralEvidenceConfidence.CANDIDATE.value,
        )
        self.assertFalse(item.metadata["structural_valid"])
        self.assertFalse(item.metadata["high_risk_eligible"])

    def test_source_confirmation_promotes_to_corroborated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "src" / "service.py"
            source.parent.mkdir()
            source.write_text("def charge():\n    return True\n", encoding="utf-8")
            with patch("ai_workflow.structural_validation.scip_ready", return_value=False):
                item = validate_crg_item(
                    root,
                    crg_item(),
                    query="who calls charge",
                    symbol="charge",
                    changed_files=[],
                    limit=10,
                )
        self.assertEqual(item.metadata["evidence_confidence"], "corroborated")
        self.assertEqual(item.metadata["confidence_basis"], ["source"])
        self.assertTrue(item.metadata["structural_valid"])
        self.assertTrue(item.metadata["high_risk_eligible"])

    def test_source_and_scip_promote_to_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "src" / "service.py"
            source.parent.mkdir()
            source.write_text("def charge():\n    return True\n", encoding="utf-8")
            scip = ContextItem(
                "scip",
                "src/service.py:1: def charge(): [definition] charge",
                10.0,
                False,
                {
                    "path": "src/service.py",
                    "symbol_name": "charge",
                    "symbol": "local charge().",
                },
            )
            with (
                patch("ai_workflow.structural_validation.scip_ready", return_value=True),
                patch("ai_workflow.structural_validation.scip_context", return_value=[scip]),
            ):
                item = validate_crg_item(
                    root,
                    crg_item(),
                    query="who calls charge",
                    symbol="charge",
                    changed_files=[],
                    limit=10,
                )
        self.assertEqual(item.metadata["evidence_confidence"], "verified")
        self.assertEqual(item.metadata["confidence_basis"], ["source", "scip"])
        self.assertEqual(item.metadata["verified_results"], 1)
        self.assertTrue(item.metadata["high_risk_eligible"])

    def test_scip_path_without_symbol_agreement_does_not_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scip = ContextItem(
                "scip",
                "src/service.py:1: unrelated",
                10.0,
                False,
                {"path": "src/service.py", "symbol_name": "unrelated"},
            )
            with (
                patch("ai_workflow.structural_validation.scip_ready", return_value=True),
                patch("ai_workflow.structural_validation.scip_context", return_value=[scip]),
            ):
                item = validate_crg_item(
                    root,
                    crg_item(),
                    query="who calls charge",
                    symbol="charge",
                    changed_files=[],
                    limit=10,
                )
        self.assertEqual(item.metadata["evidence_confidence"], "candidate")
        self.assertEqual(item.metadata["scip_confirmed_results"], 0)

    def test_verified_empty_is_not_high_risk_evidence(self):
        item = ContextItem(
            "code_review_graph",
            json.dumps(
                {
                    "status": "ok",
                    "pattern": "callers_of",
                    "result_count": 0,
                    "confidence": "verified real absence in current graph",
                    "results": [],
                }
            ),
            9.0,
            False,
            {
                "pattern": "callers_of",
                "result_count": 0,
                "empty_verified": True,
            },
        )
        with tempfile.TemporaryDirectory() as td:
            result = validate_crg_item(
                Path(td),
                item,
                query="who calls missing",
                symbol="missing",
                changed_files=[],
                limit=10,
            )
        self.assertEqual(result.metadata["evidence_confidence"], "corroborated")
        self.assertFalse(result.metadata["high_risk_eligible"])


if __name__ == "__main__":
    unittest.main()
