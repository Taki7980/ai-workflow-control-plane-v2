from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.repository_graph import graph_path, load_repository_graph
from ai_workflow.repository_registry import repository_id


class RepositoryGraphSecurityTests(unittest.TestCase):
    def _registry(self, root: Path) -> tuple[str, str]:
        config = root / "ai-workspace" / "config"
        config.mkdir(parents=True)
        frontend = repository_id("frontend", "github.com/acme/frontend")
        backend = repository_id("backend", "github.com/acme/backend")
        repositories = []
        for name, identity, repo_id in (
            ("frontend", "github.com/acme/frontend", frontend),
            ("backend", "github.com/acme/backend", backend),
        ):
            repositories.append(
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
        (config / "repositories.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "review_required": True,
                    "repositories": repositories,
                }
            ),
            encoding="utf-8",
        )
        return frontend, backend

    def test_graph_never_expands_to_unknown_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._registry(root)
            graph_path(root).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": True,
                        "edges": [
                            {
                                "source_repository_id": frontend,
                                "target_repository_id": backend,
                                "relationship": "depends_on",
                            },
                            {
                                "source_repository_id": frontend,
                                "target_repository_id": "attacker-controlled",
                                "relationship": "depends_on",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            graph = load_repository_graph(root)
            self.assertEqual(graph.edges, ())
            self.assertEqual(graph.node_ids(), {frontend, backend})

    def test_graph_rejects_policy_escape_and_unreviewed_relationships(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._registry(root)
            with self.assertRaises(ValueError):
                graph_path(root, {"workspace": {"repository_graph": "../escape.json"}})

            graph_path(root).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": False,
                        "edges": [
                            {
                                "source_repository_id": frontend,
                                "target_repository_id": backend,
                                "relationship": "deploys",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_repository_graph(root).edges, ())


if __name__ == "__main__":
    unittest.main()
