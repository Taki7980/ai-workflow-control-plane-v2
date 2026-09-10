import json
import tempfile
import unittest
from pathlib import Path


class WorkspaceGraphModelTests(unittest.TestCase):
    def test_graph_identity_is_portable_and_deterministic(self):
        from ai_workflow.workspace_graph import node_id

        first = node_id("file", "repo-a", "src/api.py", "")
        second = node_id("file", "repo-a", "src/api.py", "")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_edge_identity_is_deterministic(self):
        from ai_workflow.workspace_graph import edge_id

        first = edge_id("IMPORTS", "node-a", "node-b", "src/api.py:4")
        second = edge_id("IMPORTS", "node-a", "node-b", "src/api.py:4")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_graph_round_trip_is_stable_and_excludes_absolute_paths(self):
        from ai_workflow.workspace_graph import (
            GraphEdge,
            GraphNode,
            WorkspaceGraph,
            load_workspace_graph,
            save_workspace_graph,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node_b = GraphNode(
                node_id="b",
                kind="file",
                repository_id="repo-b",
                repository_path="backend",
                path="src/b.py",
                symbol="",
                label="src/b.py",
                fingerprint="fp-b",
                evidence="src/b.py",
            )
            node_a = GraphNode(
                node_id="a",
                kind="repository",
                repository_id="repo-a",
                repository_path="frontend",
                path=".",
                symbol="",
                label="frontend",
                fingerprint="fp-a",
                evidence="frontend",
            )
            edge = GraphEdge(
                edge_id="edge",
                edge_type="CONTAINS",
                source_node_id="a",
                target_node_id="b",
                source_repository_id="repo-a",
                target_repository_id="repo-b",
                evidence_path="src/b.py",
                evidence_line=None,
                extractor="containment",
                confidence=1.0,
                fingerprint="edge-fp",
            )
            graph = WorkspaceGraph(nodes=(node_b, node_a), edges=(edge,))
            state = {
                "schema_version": 1,
                "aggregate_workspace_fingerprint": "workspace-fp",
                "repository_fingerprints": {"repo-a": "fp-a", "repo-b": "fp-b"},
                "graph_fingerprint": "graph-fp",
                "node_count": 2,
                "edge_count": 1,
                "extractor_version": 1,
            }

            save_workspace_graph(root, graph, state)
            loaded, loaded_state = load_workspace_graph(root)

            self.assertIsNotNone(loaded)
            self.assertEqual(tuple(node.node_id for node in loaded.nodes), ("a", "b"))
            self.assertEqual(loaded.edges, (edge,))
            self.assertEqual(loaded_state["graph_fingerprint"], "graph-fp")

            generated = root / "ai-workspace/generated"
            node_lines = (generated / "workspace-graph-nodes.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(node_lines[0])["node_id"], "a")
            self.assertNotIn(str(root.resolve()), (generated / "workspace-graph-nodes.jsonl").read_text(encoding="utf-8"))
            self.assertNotIn(str(root.resolve()), (generated / "workspace-graph-edges.jsonl").read_text(encoding="utf-8"))
            self.assertNotIn(str(root.resolve()), (generated / "workspace-graph-state.json").read_text(encoding="utf-8"))

    def test_malformed_graph_state_fails_closed(self):
        from ai_workflow.workspace_graph import load_workspace_graph

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generated = root / "ai-workspace/generated"
            generated.mkdir(parents=True)
            (generated / "workspace-graph-state.json").write_text("{broken", encoding="utf-8")

            graph, state = load_workspace_graph(root)

            self.assertIsNone(graph)
            self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main()
