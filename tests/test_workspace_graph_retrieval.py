from __future__ import annotations

import unittest

from ai_workflow.models import ContextItem
from ai_workflow.workspace_graph import GraphEdge, GraphNode, WorkspaceGraph


def node(
    node_id: str,
    kind: str,
    repo: str,
    repo_path: str,
    path: str,
    *,
    symbol: str = "",
    label: str = "",
) -> GraphNode:
    return GraphNode(
        node_id=node_id,
        kind=kind,
        repository_id=repo,
        repository_path=repo_path,
        path=path,
        symbol=symbol,
        label=label or symbol or path,
        fingerprint=f"fp-{repo}",
        evidence=path,
    )


def edge(
    edge_id: str,
    edge_type: str,
    source: GraphNode,
    target: GraphNode,
    *,
    confidence: float = 1.0,
) -> GraphEdge:
    return GraphEdge(
        edge_id=edge_id,
        edge_type=edge_type,
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        source_repository_id=source.repository_id,
        target_repository_id=target.repository_id,
        evidence_path=source.path,
        evidence_line=1,
        extractor="test",
        confidence=confidence,
        fingerprint=edge_id,
    )


class WorkspaceGraphRetrievalTests(unittest.TestCase):
    def graph(self):
        frontend_repo = node("r-front", "repository", "repo-front", "frontend", ".")
        frontend_client = node(
            "f-client",
            "file",
            "repo-front",
            "frontend",
            "src/client.ts",
            label="payment client",
        )
        backend_endpoint = node(
            "e-pay",
            "endpoint",
            "repo-back",
            "backend",
            "src/api.py",
            symbol="/api/payments",
            label="POST /api/payments",
        )
        backend_handler = node(
            "f-handler",
            "file",
            "repo-back",
            "backend",
            "src/api.py",
            label="payment handler",
        )
        backend_service = node(
            "s-service",
            "symbol",
            "repo-back",
            "backend",
            "src/service.py",
            symbol="ProcessPayment",
            label="ProcessPayment",
        )
        inactive = node(
            "f-secret",
            "file",
            "repo-inactive",
            "inactive",
            "secret/payment.py",
            label="payment secret",
        )
        return WorkspaceGraph(
            nodes=(
                frontend_repo,
                frontend_client,
                backend_endpoint,
                backend_handler,
                backend_service,
                inactive,
            ),
            edges=(
                edge("c1", "CONTAINS", frontend_repo, frontend_client),
                edge("api", "CALLS_API", frontend_client, backend_endpoint, confidence=0.9),
                edge("impl", "IMPLEMENTS_ENDPOINT", backend_handler, backend_endpoint),
                edge("service", "IMPORTS", backend_handler, backend_service),
                edge("inactive", "IMPORTS", backend_service, inactive),
            ),
        )

    def config(self, **overrides):
        graph = {
            "enabled": True,
            "max_hops": 2,
            "max_nodes": 24,
            "max_edges": 40,
            "max_context_chars": 3000,
            "min_edge_confidence": 0.8,
            "build_on_demand": True,
        }
        graph.update(overrides)
        return {"workspace": {"graph": graph}}

    def test_seed_item_expands_bidirectionally_to_backend_handler(self):
        from ai_workflow.workspace_graph_retrieval import retrieve_workspace_graph

        seed = ContextItem(
            "targeted_source",
            "frontend payment client",
            metadata={"repository_id": "repo-front", "file": "src/client.ts"},
        )
        result = retrieve_workspace_graph(
            self.graph(),
            "where is the payment handler",
            {"repo-front", "repo-back"},
            seed_items=(seed,),
            graph_fingerprint="graph-fp",
            config=self.config(),
        )

        paths = {
            (item.metadata["repository_id"], item.metadata["graph_node_id"])
            for item in result.items
        }
        self.assertIn(("repo-back", "f-handler"), paths)
        self.assertNotIn(("repo-inactive", "f-secret"), paths)
        self.assertGreaterEqual(result.diagnostics["cross_repo_edges"], 1)
        self.assertLessEqual(result.diagnostics["hops_used"], 2)

    def test_endpoint_seed_is_exact_and_respects_one_hop_limit(self):
        from ai_workflow.workspace_graph_retrieval import retrieve_workspace_graph

        result = retrieve_workspace_graph(
            self.graph(),
            "payment",
            {"repo-front", "repo-back"},
            endpoint="/api/payments",
            graph_fingerprint="graph-fp",
            config=self.config(max_hops=1),
        )

        ids = {item.metadata["graph_node_id"] for item in result.items}
        self.assertIn("e-pay", ids)
        self.assertIn("f-handler", ids)
        self.assertNotIn("s-service", ids)
        self.assertLessEqual(result.diagnostics["hops_used"], 1)

    def test_hard_caps_and_context_budget_are_never_exceeded(self):
        from ai_workflow.workspace_graph_retrieval import retrieve_workspace_graph

        result = retrieve_workspace_graph(
            self.graph(),
            "payment",
            {"repo-front", "repo-back"},
            endpoint="/api/payments",
            graph_fingerprint="graph-fp",
            config=self.config(max_nodes=2, max_edges=1, max_context_chars=180),
        )

        self.assertLessEqual(result.diagnostics["expanded_nodes"], 2)
        self.assertLessEqual(result.diagnostics["expanded_edges"], 1)
        self.assertLessEqual(
            result.diagnostics["budget"]["used_context_chars"],
            180,
        )
        self.assertLessEqual(sum(len(item.text) for item in result.items), 180)

    def test_ordering_is_deterministic_and_provenance_is_portable(self):
        from ai_workflow.workspace_graph_retrieval import retrieve_workspace_graph

        kwargs = dict(
            query="payment handler",
            selected_repository_ids={"repo-front", "repo-back"},
            endpoint="/api/payments",
            graph_fingerprint="graph-fp",
            config=self.config(),
        )
        first = retrieve_workspace_graph(self.graph(), **kwargs)
        second = retrieve_workspace_graph(self.graph(), **kwargs)

        self.assertEqual(first.items, second.items)
        self.assertEqual(first.diagnostics, second.diagnostics)
        for item in first.items:
            self.assertEqual(item.source, "workspace_graph")
            self.assertIn("graph_node_id", item.metadata)
            self.assertIn("graph_edge_ids", item.metadata)
            self.assertIn("graph_distance", item.metadata)
            self.assertEqual(item.metadata["graph_fingerprint"], "graph-fp")
            self.assertNotIn("root", item.metadata)
            self.assertNotIn("workspace_root", item.metadata)
            self.assertNotIn("root", item.provenance)
            self.assertNotIn("workspace_root", item.provenance)

    def test_low_confidence_edge_is_not_traversed(self):
        from ai_workflow.workspace_graph_retrieval import retrieve_workspace_graph

        graph = self.graph()
        edges = tuple(
            GraphEdge(
                **{
                    **edge.__dict__,
                    "confidence": 0.5 if edge.edge_id == "service" else edge.confidence,
                }
            )
            for edge in graph.edges
        )
        graph = WorkspaceGraph(graph.nodes, edges)

        result = retrieve_workspace_graph(
            graph,
            "ProcessPayment",
            {"repo-front", "repo-back"},
            endpoint="/api/payments",
            graph_fingerprint="graph-fp",
            config=self.config(min_edge_confidence=0.8),
        )
        ids = {item.metadata["graph_node_id"] for item in result.items}
        self.assertNotIn("s-service", ids)


if __name__ == "__main__":
    unittest.main()
