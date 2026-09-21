from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.multi_repo_retrieval import plan_repository_retrieval
from ai_workflow.repository_registry import repository_id


class MultiRepoRetrievalTests(unittest.TestCase):
    def _workspace(self, root: Path):
        cfg = root / "ai-workspace" / "config"
        cfg.mkdir(parents=True)
        specs = []
        ids = {}
        for name in ("frontend", "backend", "worker", "unrelated"):
            repo = root / name
            repo.mkdir()
            (repo / ".git").mkdir()
            identity = f"github.com/acme/{name}"
            repo_id = repository_id(name, identity)
            ids[name] = repo_id
            specs.append(
                {
                    "repository_id": repo_id,
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
        (cfg / "repositories.json").write_text(
            json.dumps({"version": 1, "review_required": True, "repositories": specs}),
            encoding="utf-8",
        )
        (cfg / "repository-graph.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "review_required": True,
                    "edges": [
                        {
                            "source_repository_id": ids["frontend"],
                            "target_repository_id": ids["backend"],
                            "relationship": "depends_on",
                        },
                        {
                            "source_repository_id": ids["worker"],
                            "target_repository_id": ids["backend"],
                            "relationship": "consumes_schema",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        roots = [root / name for name in ("frontend", "backend", "worker", "unrelated")]
        config = {
            "workspace": {
                "max_roots": 4,
                "registry": "ai-workspace/config/repositories.json",
                "repository_graph": "ai-workspace/config/repository-graph.json",
                "hierarchical_retrieval": {
                    "enabled": True,
                    "max_primary_repositories": 2,
                    "max_graph_expansions": 1,
                    "relationships": [
                        "depends_on",
                        "publishes_api",
                        "consumes_schema",
                        "deploys",
                    ],
                },
            }
        }
        return ids, roots, config

    def test_changed_repository_is_primary_and_only_reviewed_neighbor_expands(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            plan = plan_repository_retrieval(
                root,
                roots,
                "fix checkout validation",
                ["frontend/src/checkout.ts"],
                config,
            )
            self.assertEqual(plan.primary_repository_ids, (ids["frontend"],))
            self.assertEqual(plan.expanded_repository_ids, (ids["backend"],))
            self.assertEqual([item.root.name for item in plan.repositories], ["frontend", "backend"])
            self.assertEqual(plan.repositories[1].prior, 0.85)
            self.assertIn(ids["unrelated"], plan.skipped_repository_ids)

    def test_explicit_repository_anchor_beats_default_fanout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            plan = plan_repository_retrieval(
                root,
                roots,
                "update the worker retry policy",
                [],
                config,
            )
            self.assertEqual(plan.primary_repository_ids, (ids["worker"],))
            self.assertEqual(plan.expanded_repository_ids, (ids["backend"],))

    def test_incoming_reviewed_edge_can_supply_contract_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            plan = plan_repository_retrieval(
                root,
                roots,
                "change backend schema",
                ["backend/schema/order.json"],
                config,
            )
            self.assertEqual(plan.primary_repository_ids, (ids["backend"],))
            self.assertEqual(plan.expanded_repository_ids, (ids["worker"],))
            self.assertEqual(plan.repositories[1].relationship, "consumes_schema")

    def test_missing_graph_never_broadens_default_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            (root / "ai-workspace/config/repository-graph.json").unlink()
            plan = plan_repository_retrieval(root, roots, "generic task", [], config)
            self.assertEqual([item.root.name for item in plan.repositories], ["frontend"])
            self.assertEqual(plan.expanded_repository_ids, ())
            self.assertEqual(len(plan.skipped_repository_ids), 3)

    def test_invalid_graph_fails_closed_instead_of_partial_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            graph = root / "ai-workspace/config/repository-graph.json"
            payload = json.loads(graph.read_text(encoding="utf-8"))
            payload["edges"].append(
                {
                    "source_repository_id": ids["frontend"],
                    "target_repository_id": "attacker",
                    "relationship": "depends_on",
                }
            )
            graph.write_text(json.dumps(payload), encoding="utf-8")
            plan = plan_repository_retrieval(
                root, roots, "frontend checkout", [], config
            )
            self.assertEqual(plan.primary_repository_ids, (ids["frontend"],))
            self.assertEqual(plan.expanded_repository_ids, ())

    def test_graph_expansion_respects_fanout_and_workspace_root_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            config["workspace"]["max_roots"] = 1
            plan = plan_repository_retrieval(
                root,
                roots,
                "frontend checkout",
                [],
                config,
            )
            self.assertEqual(len(plan.repositories), 1)
            self.assertEqual(plan.repositories[0].repository_id, ids["frontend"])

    def test_disabled_hierarchical_retrieval_keeps_primary_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ids, roots, config = self._workspace(root)
            config["workspace"]["hierarchical_retrieval"]["enabled"] = False
            plan = plan_repository_retrieval(root, roots, "worker task", [], config)
            self.assertEqual(plan.primary_repository_ids, (ids["worker"],))
            self.assertEqual(plan.expanded_repository_ids, ())


if __name__ == "__main__":
    unittest.main()
