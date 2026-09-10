from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.workspace_selector import RepositoryCandidate


class WorkspaceGraphBuilderTests(unittest.TestCase):
    def _candidate(self, root: Path, repo_id: str, repo_path: str, fingerprint: str):
        return RepositoryCandidate(
            root=root,
            repository_id=repo_id,
            repository_path=repo_path,
            remote_identity=f"github.com/acme/{repo_path}",
            fingerprint=fingerprint,
            changed_files=(),
            is_primary=False,
        )

    def _fixture(self, workspace: Path):
        frontend = workspace / "frontend"
        backend = workspace / "backend"
        inactive = workspace / "inactive"
        for root in (frontend, backend, inactive):
            root.mkdir(parents=True)

        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "name": "@acme/frontend",
                    "dependencies": {"@acme/backend": "workspace:*"},
                }
            ),
            encoding="utf-8",
        )
        (backend / "package.json").write_text(
            json.dumps({"name": "@acme/backend"}),
            encoding="utf-8",
        )
        (inactive / "package.json").write_text(
            json.dumps({"name": "@acme/inactive"}),
            encoding="utf-8",
        )

        (frontend / "src").mkdir()
        (backend / "src").mkdir()
        (backend / "tests").mkdir()

        (frontend / "src/client.ts").write_text(
            'import { charge } from "@acme/backend";\n'
            'export async function pay() { return fetch("/api/payments"); }\n',
            encoding="utf-8",
        )
        (backend / "src/api.py").write_text(
            '@app.post("/api/payments")\n'
            "def charge():\n"
            "    return {'ok': True}\n",
            encoding="utf-8",
        )
        (backend / "tests/test_api.py").write_text(
            "def test_charge():\n"
            "    assert True\n",
            encoding="utf-8",
        )
        (inactive / "tempting.ts").write_text(
            'fetch("/api/payments")\n',
            encoding="utf-8",
        )

        generated = workspace / "ai-workspace/generated"
        generated.mkdir(parents=True)
        (generated / "endpoint-index.jsonl").write_text(
            json.dumps(
                {
                    "method": "POST",
                    "path": "/api/payments",
                    "file": "backend/src/api.py",
                    "line": 1,
                    "parser": "regex",
                    "sha256": "endpoint-sha",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        candidates = [
            self._candidate(frontend, "repo-frontend", "frontend", "fp-frontend"),
            self._candidate(backend, "repo-backend", "backend", "fp-backend"),
        ]
        return frontend, backend, inactive, candidates

    def test_build_graph_uses_active_repositories_and_exact_evidence_edges(self):
        from ai_workflow.workspace_graph_builder import build_workspace_graph

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _, _, _, candidates = self._fixture(workspace)
            config = default_config()

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "workspace-fp"},
            ):
                graph, state = build_workspace_graph(workspace, config, force=True)

            repo_ids = {node.repository_id for node in graph.nodes}
            self.assertEqual(repo_ids, {"repo-frontend", "repo-backend"})
            self.assertNotIn("repo-inactive", repo_ids)

            cross = {
                (
                    edge.edge_type,
                    edge.source_repository_id,
                    edge.target_repository_id,
                )
                for edge in graph.edges
                if edge.source_repository_id != edge.target_repository_id
            }
            self.assertIn(
                ("DEPENDS_ON", "repo-frontend", "repo-backend"),
                cross,
            )
            self.assertIn(
                ("IMPORTS", "repo-frontend", "repo-backend"),
                cross,
            )
            self.assertIn(
                ("CALLS_API", "repo-frontend", "repo-backend"),
                cross,
            )
            self.assertTrue(
                any(
                    edge.edge_type == "IMPLEMENTS_ENDPOINT"
                    and edge.source_repository_id == "repo-backend"
                    and edge.target_repository_id == "repo-backend"
                    for edge in graph.edges
                )
            )
            self.assertTrue(
                any(
                    edge.edge_type == "TESTS"
                    and edge.source_repository_id == "repo-backend"
                    and edge.target_repository_id == "repo-backend"
                    for edge in graph.edges
                )
            )
            self.assertEqual(state["aggregate_workspace_fingerprint"], "workspace-fp")
            self.assertEqual(state["node_count"], len(graph.nodes))
            self.assertEqual(state["edge_count"], len(graph.edges))
            self.assertEqual(
                state["repository_fingerprints"],
                {"repo-backend": "fp-backend", "repo-frontend": "fp-frontend"},
            )

    def test_repeated_build_is_deterministic_and_reuses_unchanged_graph(self):
        from ai_workflow.workspace_graph_builder import build_workspace_graph

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _, _, _, candidates = self._fixture(workspace)
            config = default_config()

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "workspace-fp"},
            ):
                first_graph, first_state = build_workspace_graph(
                    workspace, config, force=True
                )
                second_graph, second_state = build_workspace_graph(
                    workspace, config, force=False
                )

            self.assertEqual(first_graph, second_graph)
            self.assertEqual(
                first_state["graph_fingerprint"],
                second_state["graph_fingerprint"],
            )
            self.assertTrue(second_state["reused"])

    def test_serialized_graph_never_contains_checkout_root(self):
        from ai_workflow.workspace_graph_builder import build_workspace_graph

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _, _, _, candidates = self._fixture(workspace)
            config = default_config()

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "workspace-fp"},
            ):
                build_workspace_graph(workspace, config, force=True)

            generated = workspace / "ai-workspace/generated"
            persisted = "\n".join(
                (generated / name).read_text(encoding="utf-8")
                for name in (
                    "workspace-graph-nodes.jsonl",
                    "workspace-graph-edges.jsonl",
                    "workspace-graph-state.json",
                )
            )
            self.assertNotIn(str(workspace.resolve()), persisted)

    def test_graph_status_reports_missing_ready_and_stale(self):
        from ai_workflow.workspace_graph_builder import (
            build_workspace_graph,
            graph_status,
        )

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _, _, _, candidates = self._fixture(workspace)
            config = default_config()

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "workspace-fp"},
            ):
                self.assertEqual(graph_status(workspace, config)["status"], "missing")
                build_workspace_graph(workspace, config, force=True)
                ready = graph_status(workspace, config)
                self.assertEqual(ready["status"], "ready")
                self.assertTrue(ready["reusable"])

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "changed-workspace-fp"},
            ):
                stale = graph_status(workspace, config)
            self.assertEqual(stale["status"], "stale")
            self.assertFalse(stale["reusable"])


if __name__ == "__main__":
    unittest.main()
