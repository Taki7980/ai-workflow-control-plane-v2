from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.config import default_config
from ai_workflow.workspace_selector import RepositoryCandidate


class WorkspaceGraphAdversarialTests(unittest.TestCase):
    def _candidate(
        self,
        root: Path,
        index: int,
        *,
        name: str | None = None,
    ) -> RepositoryCandidate:
        repo_name = name or f"service-{index}"
        return RepositoryCandidate(
            root=root,
            repository_id=f"repo-{index}",
            repository_path=repo_name,
            remote_identity=f"github.com/acme/{repo_name}",
            fingerprint=f"fp-{index}",
            changed_files=(),
            is_primary=False,
        )

    def _workspace(self, root: Path):
        candidates: list[RepositoryCandidate] = []
        for index in range(10):
            name = (
                "frontend"
                if index == 0
                else "backend"
                if index == 1
                else "shared"
                if index == 2
                else f"service-{index}"
            )
            repo = root / name
            (repo / "src").mkdir(parents=True)
            (repo / "src/service.py").write_text(
                f"def SharedName():\n    return {index}\n",
                encoding="utf-8",
            )
            if index < 9:
                candidates.append(self._candidate(repo, index, name=name))

        frontend = root / "frontend"
        backend = root / "backend"
        shared = root / "shared"
        decoy = root / "service-3"
        inactive = root / "service-9"

        (frontend / "package.json").write_text(
            json.dumps(
                {
                    "name": "@acme/frontend",
                    "dependencies": {"@acme/shared": "workspace:*"},
                }
            ),
            encoding="utf-8",
        )
        (shared / "package.json").write_text(
            json.dumps({"name": "@acme/shared"}),
            encoding="utf-8",
        )
        (backend / "package.json").write_text(
            json.dumps({"name": "@acme/backend"}),
            encoding="utf-8",
        )
        (frontend / "src/client.ts").write_text(
            'import { shared } from "@acme/shared";\n'
            'fetch("/api/payments", { method: "POST" });\n',
            encoding="utf-8",
        )
        (backend / "src/api.py").write_text(
            '@app.post("/api/payments")\n'
            "def ProcessPayment():\n"
            "    return True\n",
            encoding="utf-8",
        )
        (backend / "src/test_api.py").write_text(
            "def test_ProcessPayment():\n"
            "    assert True\n",
            encoding="utf-8",
        )
        (decoy / "src/api.py").write_text(
            '@app.get("/api/payments")\n'
            "def unrelated():\n"
            "    return False\n",
            encoding="utf-8",
        )
        (inactive / "src/api.py").write_text(
            '@app.post("/api/payments")\n'
            "def tempting():\n"
            "    return False\n",
            encoding="utf-8",
        )

        generated = root / "ai-workspace/generated"
        generated.mkdir(parents=True)
        rows = [
            {
                "method": "POST",
                "path": "/api/payments",
                "file": "backend/src/api.py",
                "line": 1,
                "parser": "regex",
                "sha256": "backend-endpoint",
            },
            {
                "method": "GET",
                "path": "/api/payments",
                "file": "service-3/src/api.py",
                "line": 1,
                "parser": "regex",
                "sha256": "decoy-endpoint",
            },
            {
                "method": "POST",
                "path": "/api/payments",
                "file": "service-9/src/api.py",
                "line": 1,
                "parser": "regex",
                "sha256": "inactive-endpoint",
            },
        ]
        (generated / "endpoint-index.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        return candidates

    def test_ten_repo_fixture_keeps_only_evidence_backed_active_edges(self):
        from ai_workflow.workspace_graph_builder import build_workspace_graph

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            candidates = self._workspace(workspace)
            config = default_config()
            config["workspace"]["max_roots"] = 12

            with patch(
                "ai_workflow.workspace_graph_builder.build_repository_candidates",
                return_value=candidates,
            ), patch(
                "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                return_value={"fingerprint": "workspace-fp"},
            ):
                graph, state = build_workspace_graph(workspace, config, force=True)

            repo_ids = {node.repository_id for node in graph.nodes}
            self.assertEqual(len(repo_ids), 9)
            self.assertNotIn("repo-9", repo_ids)

            api_edges = [
                edge
                for edge in graph.edges
                if edge.edge_type == "CALLS_API"
                and edge.source_repository_id == "repo-0"
            ]
            self.assertEqual(
                [
                    (
                        edge.source_repository_id,
                        edge.target_repository_id,
                    )
                    for edge in api_edges
                ],
                [("repo-0", "repo-1")],
            )
            self.assertTrue(
                any(
                    edge.edge_type == "DEPENDS_ON"
                    and edge.source_repository_id == "repo-0"
                    and edge.target_repository_id == "repo-2"
                    for edge in graph.edges
                )
            )
            self.assertTrue(
                any(
                    edge.edge_type == "IMPORTS"
                    and edge.source_repository_id == "repo-0"
                    and edge.target_repository_id == "repo-2"
                    for edge in graph.edges
                )
            )
            self.assertTrue(
                any(
                    edge.edge_type == "TESTS"
                    and edge.source_repository_id == "repo-1"
                    for edge in graph.edges
                )
            )
            self.assertEqual(state["node_count"], len(graph.nodes))
            self.assertEqual(state["edge_count"], len(graph.edges))

    def test_graph_identity_survives_workspace_relocation(self):
        from ai_workflow.workspace_graph_builder import build_workspace_graph

        fingerprints = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                candidates = self._workspace(workspace)
                config = default_config()
                config["workspace"]["max_roots"] = 12
                with patch(
                    "ai_workflow.workspace_graph_builder.build_repository_candidates",
                    return_value=candidates,
                ), patch(
                    "ai_workflow.workspace_graph_builder.aggregate_workspace_fingerprint",
                    return_value={"fingerprint": "workspace-fp"},
                ):
                    _, state = build_workspace_graph(
                        workspace,
                        config,
                        force=True,
                    )
                fingerprints.append(state["graph_fingerprint"])

        self.assertEqual(fingerprints[0], fingerprints[1])


if __name__ == "__main__":
    unittest.main()
