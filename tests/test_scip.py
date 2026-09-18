import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_workflow.scip import (
    any_scip_ready,
    detect_indexer,
    items_from_scip_payload,
    scip_context,
    scip_data_dir,
    scip_status,
    sync_scip_index,
)


class ScipIndexerDetectionTests(unittest.TestCase):
    def test_detects_supported_language_indexers(self):
        cases = [
            (
                "python",
                {"pyproject.toml": "[project]\nname='demo'\n", "app.py": "def run():\n    pass\n"},
                "scip-python",
                ("index", "."),
            ),
            (
                "typescript",
                {"package.json": "{}", "tsconfig.json": "{}", "app.ts": "export function run() {}\n"},
                "scip-typescript",
                ("index",),
            ),
            (
                "javascript",
                {"package.json": "{}", "app.js": "export function run() {}\n"},
                "scip-typescript",
                ("index", "--infer-tsconfig"),
            ),
            (
                "java",
                {"pom.xml": "<project/>", "src/Main.java": "class Main {}\n"},
                "scip-java",
                ("index",),
            ),
            (
                "go",
                {"go.mod": "module example.test/demo\n", "main.go": "package main\nfunc main() {}\n"},
                "scip-go",
                (),
            ),
        ]

        for language, files, executable, args in cases:
            with self.subTest(language=language), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                for relative, text in files.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")

                indexer = detect_indexer(root)

                self.assertIsNotNone(indexer)
                assert indexer is not None
                self.assertEqual(indexer.language, language)
                self.assertEqual(indexer.executable, executable)
                self.assertEqual(indexer.args[: len(args)], args)

    def test_polyglot_detection_fails_closed_but_override_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "go.mod").write_text(
                "module example.test/demo\n",
                encoding="utf-8",
            )
            (root / "main.go").write_text(
                "package main\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                "[project]\nname='demo'\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "def run():\n    pass\n",
                encoding="utf-8",
            )

            self.assertIsNone(detect_indexer(root))
            explicit = detect_indexer(root, "python")

        self.assertIsNotNone(explicit)
        assert explicit is not None
        self.assertEqual(explicit.language, "python")


class ScipPayloadTests(unittest.TestCase):
    def test_maps_precise_occurrences_across_target_languages(self):
        symbol = "scip . . . demo/ProcessPayment()."
        payload = {
            "documents": [
                {
                    "language": language,
                    "relativePath": path,
                    "symbols": [
                        {
                            "symbol": symbol,
                            "displayName": "ProcessPayment",
                            "kind": "Function",
                        }
                    ],
                    "occurrences": [
                        {"range": [0, 0, 14], "symbol": symbol, "symbolRoles": 1},
                        {"range": [1, 5, 19], "symbol": symbol, "symbolRoles": 0},
                    ],
                }
                for language, path in [
                    ("Python", "python/service.py"),
                    ("TypeScript", "typescript/service.ts"),
                    ("Java", "java/Service.java"),
                    ("Go", "go/service.go"),
                ]
            ]
        }

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for document in payload["documents"]:
                path = root / document["relativePath"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    "ProcessPayment\ncall ProcessPayment\n",
                    encoding="utf-8",
                )

            items = items_from_scip_payload(
                root,
                payload,
                "Find references to ProcessPayment",
                "ProcessPayment",
                [],
                20,
                patterns=("references_to",),
            )

        self.assertEqual(
            {item.metadata["language"].lower() for item in items},
            {"python", "typescript", "java", "go"},
        )
        self.assertTrue(all(item.source == "scip" for item in items))
        self.assertTrue(all(item.metadata["structural_valid"] for item in items))
        self.assertTrue(all(item.metadata["pattern"] == "references_to" for item in items))
        self.assertTrue(any(item.metadata["role"] == "reference" for item in items))

    def test_accepts_snake_case_json_fields(self):
        payload = {
            "documents": [
                {
                    "language": "Python",
                    "relative_path": "service.py",
                    "symbols": [
                        {
                            "symbol": "scip . . . service/Run().",
                            "display_name": "Run",
                            "kind": "Function",
                        }
                    ],
                    "occurrences": [
                        {
                            "range": [0, 4, 7],
                            "symbol": "scip . . . service/Run().",
                            "symbol_roles": 1,
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "service.py").write_text("def Run(): pass\n", encoding="utf-8")
            items = items_from_scip_payload(
                root,
                payload,
                "Where is Run?",
                "Run",
                [],
                5,
                patterns=("architecture",),
            )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metadata["symbol_name"], "Run")
        self.assertEqual(items[0].metadata["role"], "definition")


class ScipFreshnessTests(unittest.TestCase):
    def test_index_without_manifest_is_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = scip_data_dir(root, root)
            data_dir.mkdir(parents=True)
            (data_dir / "index.scip").write_bytes(b"placeholder")

            status = scip_status(root, root)

        self.assertFalse(status["ready"])
        self.assertIn("manifest", status["reason"])


    def _write_ready_state(
        self,
        root: Path,
        *,
        fingerprint: str = "repo-fingerprint",
        git_head: str = "head-sha",
    ) -> None:
        data_dir = scip_data_dir(root, root)
        data_dir.mkdir(parents=True, exist_ok=True)
        index_path = data_dir / "index.scip"
        json_path = data_dir / "index.json"
        index_path.write_bytes(b"scip-index")
        json_path.write_text(
            json.dumps({"documents": []}),
            encoding="utf-8",
        )
        manifest = {
            "manifest_schema": 1,
            "repository_relative_path": ".",
            "repository_fingerprint": fingerprint,
            "git_head": git_head,
            "language": "python",
            "indexer": "scip-python",
            "index_sha256": hashlib.sha256(
                index_path.read_bytes()
            ).hexdigest(),
            "json_sha256": hashlib.sha256(
                json_path.read_bytes()
            ).hexdigest(),
        }
        (data_dir / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def test_status_validates_hashes_and_repository_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_ready_state(root)

            with patch(
                "ai_workflow.scip.repository_fingerprint",
                return_value={
                    "fingerprint": "repo-fingerprint",
                    "git_head": "head-sha",
                },
            ):
                ready = scip_status(root, root)
            self.assertTrue(ready["ready"])

            data_dir = scip_data_dir(root, root)
            (data_dir / "index.scip").write_bytes(b"tampered")
            with patch(
                "ai_workflow.scip.repository_fingerprint",
                return_value={
                    "fingerprint": "repo-fingerprint",
                    "git_head": "head-sha",
                },
            ):
                tampered = scip_status(root, root)
            self.assertFalse(tampered["ready"])
            self.assertIn("hash mismatch", tampered["reason"])

            self._write_ready_state(root)
            with patch(
                "ai_workflow.scip.repository_fingerprint",
                return_value={
                    "fingerprint": "different",
                    "git_head": "head-sha",
                },
            ):
                stale = scip_status(root, root)
            self.assertFalse(stale["ready"])
            self.assertIn("fingerprint", stale["reason"])

    def test_any_scip_ready_short_circuits_on_ready_repository(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch(
                    "ai_workflow.scip.active_repository_roots",
                    return_value=[root],
                ),
                patch(
                    "ai_workflow.scip.scip_ready",
                    return_value=True,
                ),
            ):
                self.assertTrue(any_scip_ready(root, {}))
            with (
                patch(
                    "ai_workflow.scip.active_repository_roots",
                    return_value=[root],
                ),
                patch(
                    "ai_workflow.scip.scip_ready",
                    return_value=False,
                ),
            ):
                self.assertFalse(any_scip_ready(root, {}))

    def test_unavailable_scip_returns_empty_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            items = scip_context(
                root,
                "Who calls ProcessPayment?",
                "ProcessPayment",
                [],
                5,
                patterns=("callers_of",),
            )
        self.assertEqual(items, [])


class ScipSyncTests(unittest.TestCase):
    @staticmethod
    def _which(name: str) -> str:
        return f"/tools/{name}"

    @staticmethod
    def _successful_run(command, **kwargs):
        if "scip-python" in command[0]:
            output_index = Path(
                command[command.index("--output") + 1]
            )
            output_index.write_bytes(b"generated-index")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="indexed",
                stderr="",
            )
        if command[0].endswith("/scip") and "print" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"documents": []}),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    def test_sync_publishes_central_index_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "pyproject.toml").write_text(
                "[project]\nname='demo'\n",
                encoding="utf-8",
            )
            (root / "app.py").write_text(
                "def run():\n    pass\n",
                encoding="utf-8",
            )

            with (
                patch(
                    "ai_workflow.scip.shutil.which",
                    side_effect=self._which,
                ),
                patch(
                    "ai_workflow.scip.subprocess.run",
                    side_effect=self._successful_run,
                ) as run,
                patch(
                    "ai_workflow.scip.repository_fingerprint",
                    return_value={
                        "fingerprint": "repo-fingerprint",
                        "git_head": "head-sha",
                    },
                ),
            ):
                status = sync_scip_index(
                    root,
                    root,
                    language="python",
                    timeout_seconds=12,
                )

            self.assertTrue(status["ready"])
            data_dir = scip_data_dir(root, root)
            self.assertTrue((data_dir / "index.scip").is_file())
            self.assertTrue((data_dir / "index.json").is_file())
            self.assertTrue((data_dir / "manifest.json").is_file())
            index_command = run.call_args_list[0].args[0]
            print_command = run.call_args_list[1].args[0]
            self.assertEqual(index_command[0], "/tools/scip-python")
            self.assertIn("--output", index_command)
            self.assertEqual(
                print_command,
                [
                    "/tools/scip",
                    "print",
                    "--json",
                    str(data_dir / "index.scip"),
                ],
            )

    def test_sync_builds_go_command_with_output_before_packages(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[0].endswith("/scip-go"):
                output_index = Path(
                    command[command.index("--output") + 1]
                )
                output_index.write_bytes(b"go-index")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"documents": []}),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch(
                    "ai_workflow.scip.shutil.which",
                    side_effect=self._which,
                ),
                patch(
                    "ai_workflow.scip.subprocess.run",
                    side_effect=run,
                ),
                patch(
                    "ai_workflow.scip.repository_fingerprint",
                    return_value={
                        "fingerprint": "repo-fingerprint",
                        "git_head": "head-sha",
                    },
                ),
            ):
                status = sync_scip_index(
                    root,
                    root,
                    language="go",
                )

        self.assertTrue(status["ready"])
        self.assertEqual(commands[0][0], "/tools/scip-go")
        self.assertEqual(commands[0][-1], "./...")
        self.assertLess(
            commands[0].index("--output"),
            commands[0].index("./..."),
        )

    def test_sync_reports_missing_tools_and_indexer_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            with patch(
                "ai_workflow.scip.shutil.which",
                return_value=None,
            ):
                missing_scip = sync_scip_index(
                    root,
                    root,
                    language="python",
                )
            self.assertIn("scip CLI", missing_scip["reason"])

            def only_scip(name: str):
                return "/tools/scip" if name == "scip" else None

            with patch(
                "ai_workflow.scip.shutil.which",
                side_effect=only_scip,
            ):
                missing_indexer = sync_scip_index(
                    root,
                    root,
                    language="python",
                )
            self.assertIn(
                "scip-python is not installed",
                missing_indexer["reason"],
            )

            with (
                patch(
                    "ai_workflow.scip.shutil.which",
                    side_effect=self._which,
                ),
                patch(
                    "ai_workflow.scip.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["scip-python"],
                        1,
                        stdout="",
                        stderr="indexer failed",
                    ),
                ),
            ):
                failed = sync_scip_index(
                    root,
                    root,
                    language="python",
                )
            self.assertIn("indexer failed", failed["reason"])

    def test_sync_rejects_invalid_print_json(self):
        calls = 0

        def run(command, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                output_index = Path(
                    command[command.index("--output") + 1]
                )
                output_index.write_bytes(b"index")
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="{not-json",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch(
                    "ai_workflow.scip.shutil.which",
                    side_effect=self._which,
                ),
                patch(
                    "ai_workflow.scip.subprocess.run",
                    side_effect=run,
                ),
            ):
                result = sync_scip_index(
                    root,
                    root,
                    language="python",
                )

        self.assertFalse(result["ready"])
        self.assertIn("invalid JSON", result["reason"])


if __name__ == "__main__":
    unittest.main()
