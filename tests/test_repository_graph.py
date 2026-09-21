from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_workflow.repository_graph import (
    RepositoryRelationship,
    graph_path,
    graph_summary,
    load_repository_graph,
)
from ai_workflow.repository_registry import (
    discover_repositories,
    registry_payload,
    repository_id,
)


class RepositoryGraphTests(unittest.TestCase):
    def _git_repo(self, root: Path, name: str, remote: str) -> None:
        repo = root / name
        repo.mkdir()
        git = repo / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git / "refs" / "heads" / "main").write_text("a" * 40 + "\n", encoding="utf-8")
        (git / "config").write_text(
            f'[remote "origin"]\n\turl = {remote}\n',
            encoding="utf-8",
        )

    def _workspace(self, root: Path) -> tuple[str, str]:
        self._git_repo(root, "frontend", "https://github.com/acme/frontend.git")
        self._git_repo(root, "backend", "https://github.com/acme/backend.git")
        registry = root / "ai-workspace" / "config" / "repositories.json"
        registry.parent.mkdir(parents=True)
        payload = registry_payload(discover_repositories(root, max_depth=1))
        for entry in payload["repositories"]:
            entry["included"] = True
            entry["reason"] = "manual"
        registry.write_text(json.dumps(payload), encoding="utf-8")
        ids = {
            entry["relative_path"]: entry["repository_id"]
            for entry in payload["repositories"]
        }
        return ids["frontend"], ids["backend"]

    def _write_graph(self, root: Path, edges: list[dict]) -> None:
        graph_path(root).write_text(
            json.dumps({"version": 1, "review_required": True, "edges": edges}),
            encoding="utf-8",
        )

    def test_explicit_relationships_use_stable_repository_ids(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._workspace(root)
            self._write_graph(
                root,
                [
                    {
                        "source_repository_id": frontend,
                        "target_repository_id": backend,
                        "relationship": "depends_on",
                    },
                    {
                        "source_repository_id": backend,
                        "target_repository_id": frontend,
                        "relationship": "publishes_api",
                    },
                ],
            )

            graph = load_repository_graph(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 2)
            self.assertEqual(
                graph.neighbors(frontend, [RepositoryRelationship.DEPENDS_ON]),
                (backend,),
            )
            self.assertEqual(len(graph.edges[0].edge_id), 64)
            self.assertEqual(len(graph.fingerprint), 64)
            self.assertEqual(graph.fingerprint, load_repository_graph(root).fingerprint)

    def test_unknown_repository_fails_closed_for_all_edges(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._workspace(root)
            self._write_graph(
                root,
                [
                    {
                        "source_repository_id": frontend,
                        "target_repository_id": backend,
                        "relationship": "depends_on",
                    },
                    {
                        "source_repository_id": frontend,
                        "target_repository_id": "untrusted-unknown-id",
                        "relationship": "depends_on",
                    },
                ],
            )
            graph = load_repository_graph(root)
            self.assertEqual(graph.edges, ())

    def test_excluded_repository_cannot_be_relationship_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._workspace(root)
            registry = root / "ai-workspace" / "config" / "repositories.json"
            payload = json.loads(registry.read_text(encoding="utf-8"))
            for entry in payload["repositories"]:
                if entry["repository_id"] == backend:
                    entry["included"] = False
            registry.write_text(json.dumps(payload), encoding="utf-8")
            self._write_graph(
                root,
                [{
                    "source_repository_id": frontend,
                    "target_repository_id": backend,
                    "relationship": "depends_on",
                }],
            )
            graph = load_repository_graph(root)
            self.assertEqual(graph.edges, ())
            self.assertEqual(graph.node_ids(), {frontend})

    def test_unknown_relationship_self_edge_and_duplicate_fail_closed(self):
        cases = [
            lambda a, b: [{"source_repository_id": a, "target_repository_id": b, "relationship": "controls"}],
            lambda a, b: [{"source_repository_id": a, "target_repository_id": a, "relationship": "depends_on"}],
            lambda a, b: [
                {"source_repository_id": a, "target_repository_id": b, "relationship": "depends_on"},
                {"source_repository_id": a, "target_repository_id": b, "relationship": "depends_on"},
            ],
        ]
        for build in cases:
            with self.subTest(case=build), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                frontend, backend = self._workspace(root)
                self._write_graph(root, build(frontend, backend))
                self.assertEqual(load_repository_graph(root).edges, ())

    def test_graph_path_must_stay_inside_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(ValueError):
                graph_path(root, {"workspace": {"repository_graph": "../outside.json"}})

    def test_missing_or_unreviewed_graph_grants_no_cross_repo_relationship(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._workspace(root)
            self.assertEqual(load_repository_graph(root).edges, ())
            graph_path(root).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "review_required": False,
                        "edges": [{
                            "source_repository_id": frontend,
                            "target_repository_id": backend,
                            "relationship": "deploys",
                        }],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_repository_graph(root).edges, ())

    def test_summary_contains_no_absolute_repository_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            frontend, backend = self._workspace(root)
            self._write_graph(
                root,
                [{
                    "source_repository_id": frontend,
                    "target_repository_id": backend,
                    "relationship": "consumes_schema",
                }],
            )
            summary = graph_summary(root)
            encoded_nodes = json.dumps(summary["nodes"])
            self.assertNotIn(str(root), encoded_nodes)
            self.assertEqual(summary["edges"][0]["relationship"], "consumes_schema")


if __name__ == "__main__":
    unittest.main()
