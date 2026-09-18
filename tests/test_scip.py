import tempfile
import unittest
from pathlib import Path

from ai_workflow.scip import (
    detect_indexer,
    items_from_scip_payload,
    scip_context,
    scip_data_dir,
    scip_status,
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
                "Who calls ProcessPayment?",
                "ProcessPayment",
                [],
                20,
                patterns=("callers_of",),
            )

        self.assertEqual(
            {item.metadata["language"].lower() for item in items},
            {"python", "typescript", "java", "go"},
        )
        self.assertTrue(all(item.source == "scip" for item in items))
        self.assertTrue(all(item.metadata["structural_valid"] for item in items))
        self.assertTrue(all(item.metadata["pattern"] == "callers_of" for item in items))
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


if __name__ == "__main__":
    unittest.main()
