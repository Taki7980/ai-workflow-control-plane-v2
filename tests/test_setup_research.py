import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.bootstrap import setup
from ai_workflow.research_scout import (
    Paper,
    _parse_arxiv_xml,
    _request,
    score_paper,
    title_similarity,
)


class SetupTests(unittest.TestCase):
    def test_setup_is_one_command_single_folder_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = setup(root)
            self.assertEqual(first["status"], "ready")
            self.assertEqual(first["project"], root.name)
            self.assertEqual(first["layout"], "workspace")
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".ai").exists())
            self.assertTrue((root / "ai-workspace/agents/AGENTS.md").is_file())
            self.assertTrue((root / "ai-workspace/config/control-plane.json").is_file())
            self.assertTrue((root / "ai-workspace/config/repositories.json").is_file())
            self.assertTrue((root / "ai-workspace/state/PROJECT").is_file())
            self.assertTrue((root / "ai-workspace/generated/index-state.json").is_file())

            second = setup(root)
            self.assertEqual(second["status"], "ready")
            self.assertIn("ai-workspace/agents/AGENTS.md", second["preserved"])
            self.assertIn("ai-workspace/config/control-plane.json", second["preserved"])
            self.assertIn("ai-workspace/config/repositories.json", second["preserved"])

    def test_setup_auto_detects_and_activates_nested_git_repositories(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def fake_repo(relative: str) -> None:
                repo = root / relative
                git_dir = repo / ".git"
                (git_dir / "refs/heads").mkdir(parents=True)
                (git_dir / "HEAD").write_text(
                    "ref: refs/heads/main\n",
                    encoding="utf-8",
                )
                (git_dir / "refs/heads/main").write_text(
                    "a" * 40 + "\n",
                    encoding="utf-8",
                )
                (git_dir / "config").write_text(
                    '[remote "origin"]\n'
                    f'\turl = https://example.com/{relative}.git\n',
                    encoding="utf-8",
                )

            fake_repo("admin-panel")
            fake_repo("services/backend")

            with patch(
                "ai_workflow.bootstrap.sync_workspace_graphs",
                return_value={
                    "installed": False,
                    "attempted": 0,
                    "ready": 0,
                    "repositories": [],
                },
            ):
                result = setup(root)

            registry = json.loads(
                (root / "ai-workspace/config/repositories.json").read_text(
                    encoding="utf-8"
                )
            )
            repositories = registry["repositories"]
            self.assertEqual(
                {row["relative_path"] for row in repositories},
                {"admin-panel", "services/backend"},
            )
            self.assertTrue(all(row["included"] for row in repositories))
            self.assertEqual(result["repository_registry"]["accepted"], 2)

    def test_setup_preserves_existing_legacy_agents_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agents = root / "AGENTS.md"
            agents.write_text("# Existing project rules\n", encoding="utf-8")
            result = setup(root, "Demo")
            self.assertEqual(agents.read_text(encoding="utf-8"), "# Existing project rules\n")
            self.assertIn("AGENTS.md", result["preserved"])
            self.assertTrue((root / "ai-workspace/agents/AGENTS.md").is_file())

    def test_setup_can_emit_legacy_root_files_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = setup(root, "Demo", legacy_root_files=True)
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertTrue((root / ".ai/PROJECT").is_file())
            self.assertIn("AGENTS.md", result["created"])
            self.assertIn(".ai/PROJECT", result["created"])


class ResearchScoutTests(unittest.TestCase):
    def test_relevance_scoring_prefers_control_plane_research(self):
        relevant = Paper(
            arxiv_id="2609.99999",
            title="Token-Efficient Repository Retrieval for Autonomous Coding Agents",
            summary="We study context selection, retrieval, code agents, and token budgets.",
            authors=("A. Researcher",),
            categories=("cs.AI", "cs.SE"),
            published="2026-09-07T00:00:00Z",
            updated="2026-09-07T00:00:00Z",
            doi=None,
            url="https://arxiv.org/abs/2609.99999",
        )
        unrelated = Paper(
            arxiv_id="2609.88888",
            title="A Survey of Marine Algae Pigments",
            summary="Biological observations of algae pigments in coastal water.",
            authors=("B. Researcher",),
            categories=("q-bio.OT",),
            published="2026-09-07T00:00:00Z",
            updated="2026-09-07T00:00:00Z",
            doi=None,
            url="https://arxiv.org/abs/2609.88888",
        )
        self.assertGreater(score_paper(relevant), score_paper(unrelated))
        self.assertGreaterEqual(score_paper(relevant), 6)


    def test_research_request_rejects_untrusted_scheme_before_io(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "payload.json"
            target.write_text("secret", encoding="utf-8")
            with patch(
                "ai_workflow.research_scout.urllib.request.build_opener"
            ) as opener:
                with self.assertRaisesRegex(ValueError, "trusted HTTPS"):
                    _request(target.as_uri())
                opener.assert_not_called()

    def test_arxiv_xml_rejects_doctype_and_entities(self):
        malicious = (
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE feed [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            b'<feed xmlns="http://www.w3.org/2005/Atom">&xxe;</feed>'
        )
        with self.assertRaisesRegex(ValueError, "DTD"):
            _parse_arxiv_xml(malicious)

    def test_title_similarity_supports_crossref_corroboration(self):
        a = "Retrieval-Conditioned Topology Selection for Multi-Agent Code Generation"
        b = "Retrieval Conditioned Topology Selection for Multi Agent Code Generation"
        self.assertGreaterEqual(title_similarity(a, b), 0.9)
        self.assertLess(title_similarity(a, "Quantum transport in graphene"), 0.2)


if __name__ == "__main__":
    unittest.main()
