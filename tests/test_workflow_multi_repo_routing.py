from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.budget import ContextBudget
from ai_workflow.config import default_config
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision
from ai_workflow.providers import ProviderStatus
from ai_workflow.repository_registry import repository_id
from ai_workflow.workflow_engine import WorkflowEngine


class WorkflowMultiRepoRoutingTests(unittest.TestCase):
    def test_engine_queries_primary_and_reviewed_neighbor_not_unrelated_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_dir = root / "ai-workspace" / "config"
            cfg_dir.mkdir(parents=True)
            roots = []
            entries = []
            ids = {}
            for name in ("frontend", "backend", "unrelated"):
                repo = root / name
                repo.mkdir()
                (repo / ".git").mkdir()
                identity = f"github.com/acme/{name}"
                rid = repository_id(name, identity)
                ids[name] = rid
                roots.append(repo.resolve())
                entries.append(
                    {
                        "repository_id": rid,
                        "name": name,
                        "relative_path": name,
                        "git_dir": f"{name}/.git",
                        "remote_identity": identity,
                        "head_ref": "refs/heads/main",
                        "head_sha": "a" * 40,
                        "included": True,
                        "reason": "manual",
                    }
                )
            (cfg_dir / "repositories.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "repositories": entries,
                    }
                ),
                encoding="utf-8",
            )
            (cfg_dir / "repository-graph.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "edges": [
                            {
                                "source_repository_id": ids["frontend"],
                                "target_repository_id": ids["backend"],
                                "relationship": "depends_on",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            config = default_config()
            config["workspace"]["max_roots"] = 3
            config["workspace"]["hierarchical_retrieval"] = {
                "enabled": True,
                "max_primary_repositories": 2,
                "max_graph_expansions": 1,
                "relationships": [
                    "depends_on",
                    "publishes_api",
                    "consumes_schema",
                    "deploys",
                ],
            }
            calls = []

            def base(candidate_root, *args, **kwargs):
                calls.append(candidate_root.name)
                return [
                    ContextItem(
                        "lightweight_index",
                        f"{candidate_root.name} checkout evidence",
                        2.0,
                    )
                ]

            engine = WorkflowEngine(base_gather=base)
            with patch(
                "ai_workflow.workflow_engine.workspace_roots",
                return_value=roots,
            ):
                _, diagnostics = engine.gather_detailed(
                    root,
                    "change frontend checkout",
                    RouteDecision(Lane.SMALL, Risk.LOW),
                    ContextBudget(2500, 700, 10000, {}),
                    config,
                    ProviderStatus(False, False, False, False, False),
                )

            self.assertEqual(calls, ["frontend", "backend"])
            routing = diagnostics["repository_routing"]
            self.assertEqual(routing["primary_repository_ids"], [ids["frontend"]])
            self.assertEqual(routing["expanded_repository_ids"], [ids["backend"]])
            self.assertIn(ids["unrelated"], routing["skipped_repository_ids"])
            self.assertEqual(routing["repositories"][0]["prior"], 1.0)
            self.assertLess(routing["repositories"][1]["prior"], 1.0)


if __name__ == "__main__":
    unittest.main()
