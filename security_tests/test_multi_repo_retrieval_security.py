from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.multi_repo_retrieval import plan_repository_retrieval
from ai_workflow.repository_registry import repository_id


class MultiRepoRetrievalSecurityTests(unittest.TestCase):
    def test_unreviewed_or_unknown_graph_target_cannot_expand_retrieval(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "ai-workspace" / "config"
            cfg.mkdir(parents=True)
            roots = []
            entries = []
            ids = {}
            for name in ("app", "api"):
                repo = root / name
                repo.mkdir()
                (repo / ".git").mkdir()
                identity = f"github.com/acme/{name}"
                rid = repository_id(name, identity)
                ids[name] = rid
                roots.append(repo)
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
            (cfg / "repositories.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "repositories": entries,
                    }
                ),
                encoding="utf-8",
            )
            (cfg / "repository-graph.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "edges": [
                            {
                                "source_repository_id": ids["app"],
                                "target_repository_id": "model-supplied-repository",
                                "relationship": "depends_on",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "workspace": {
                    "max_roots": 4,
                    "registry": "ai-workspace/config/repositories.json",
                    "repository_graph": "ai-workspace/config/repository-graph.json",
                    "hierarchical_retrieval": {
                        "enabled": True,
                        "max_graph_expansions": 2,
                    },
                }
            }
            plan = plan_repository_retrieval(
                root, roots, "change app login", [], config
            )
            self.assertEqual(plan.primary_repository_ids, (ids["app"],))
            self.assertEqual(plan.expanded_repository_ids, ())
            self.assertEqual([item.root.name for item in plan.repositories], ["app"])


if __name__ == "__main__":
    unittest.main()
