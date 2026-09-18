import argparse
import importlib.util
import tomllib
import unittest
from pathlib import Path

import ai_workflow
from ai_workflow import cli


def _choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


class ModularArchitectureCompatibilityTests(unittest.TestCase):
    def test_public_package_api_and_console_entrypoint_are_unchanged(self):
        self.assertEqual(
            set(ai_workflow.__all__),
            {
                "TaskRequest",
                "WorkflowClient",
                "WorkflowResult",
                "__version__",
                "prepare",
            },
        )
        pyproject = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            pyproject["project"]["scripts"]["ai-workflow"],
            "ai_workflow.entrypoint:main",
        )

    def test_cli_command_tree_is_unchanged(self):
        parser = cli.build_parser()
        top = _choices(parser)
        self.assertEqual(
            set(top),
            {
                "setup",
                "bootstrap",
                "init",
                "route",
                "repos",
                "brief",
                "context",
                "index",
                "doctor",
                "verify",
                "benchmark-corpus",
                "benchmark",
                "benchmark-ablate",
                "benchmark-algorithms",
                "benchmark-intervene",
                "benchmark-statistics",
                "benchmark-calibrate",
                "benchmark-policy-advisor",
                "learning",
                "deployment",
                "production",
                "stats",
                "handoff",
                "memory",
                "compress",
            },
        )
        self.assertEqual(
            set(_choices(top["repos"])),
            {"list", "refresh", "include", "exclude"},
        )
        self.assertEqual(
            set(_choices(top["benchmark-corpus"])),
            {"validate", "snapshot"},
        )
        self.assertEqual(
            set(_choices(top["learning"])),
            {
                "status",
                "record-outcome",
                "contextual-policy",
                "create-manifest",
                "verify-manifest",
                "shadow-evaluate",
                "evaluate",
            },
        )
        self.assertEqual(
            set(_choices(top["deployment"])),
            {
                "create",
                "status",
                "guardrails",
                "promote",
                "metrics",
                "verify-incident",
                "rollback",
            },
        )
        self.assertEqual(
            set(_choices(top["production"])),
            {"status", "sync", "reconcile"},
        )
        self.assertEqual(
            set(_choices(top["memory"])),
            {"add", "search", "list", "prune", "export"},
        )

    def test_legacy_cli_handlers_remain_importable(self):
        for name in (
            "cmd_setup",
            "cmd_benchmark",
            "cmd_learning_status",
            "cmd_deployment_create",
            "cmd_memory_add",
            "cmd_production_status",
        ):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(cli, name)))

    def test_new_domain_packages_exist(self):
        for module_name in (
            "ai_workflow.commands",
            "ai_workflow.retrieval",
            "ai_workflow.provider",
            "ai_workflow.state",
            "ai_workflow.evaluation",
        ):
            with self.subTest(module_name=module_name):
                self.assertIsNotNone(importlib.util.find_spec(module_name))


if __name__ == "__main__":
    unittest.main()
