from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_workflow import compress as compress_module
from ai_workflow import easy_setup, entrypoint, research_scout, verify as verify_module


class CompressCoverageTests(unittest.TestCase):
    def test_rtk_missing_and_success_paths(self) -> None:
        with patch("ai_workflow.compress.shutil.which", return_value=None):
            self.assertIsNone(compress_module.compress_with_rtk("payload"))

        completed = SimpleNamespace(returncode=0, stdout="packed\n")
        with (
            patch("ai_workflow.compress.shutil.which", return_value="/usr/bin/rtk"),
            patch("ai_workflow.compress.subprocess.run", return_value=completed) as run,
        ):
            result = compress_module.compress_with_rtk("payload", "json")

        self.assertEqual(result, "packed\n")
        self.assertEqual(run.call_args.args[0], ["rtk", "pipe", "--filter", "json"])

    def test_rtk_failure_and_exception_paths(self) -> None:
        for result in (
            SimpleNamespace(returncode=1, stdout="ignored"),
            SimpleNamespace(returncode=0, stdout="   "),
        ):
            with (
                self.subTest(result=result.returncode),
                patch("ai_workflow.compress.shutil.which", return_value="/usr/bin/rtk"),
                patch("ai_workflow.compress.subprocess.run", return_value=result),
            ):
                self.assertIsNone(compress_module.compress_with_rtk("payload"))

        with (
            patch("ai_workflow.compress.shutil.which", return_value="/usr/bin/rtk"),
            patch("ai_workflow.compress.subprocess.run", side_effect=OSError("boom")),
        ):
            self.assertIsNone(compress_module.compress_with_rtk("payload"))

    def test_compress_text_uses_rtk_and_enforces_both_caps(self) -> None:
        with patch("ai_workflow.compress.compress_with_rtk", return_value="rtk\n"):
            self.assertEqual(
                compress_module.compress_text("payload", prefer_rtk=True),
                "rtk\n",
            )

        text = "\n".join(str(index) for index in range(20))
        line_capped = compress_module.compress_text(text, max_lines=4)
        self.assertIn("LINES OMITTED", line_capped)
        self.assertTrue(line_capped.endswith("\n"))

        char_capped = compress_module.compress_text("x" * 200, max_chars=80)
        self.assertIn("CHARACTER CAP REACHED", char_capped)
        self.assertLessEqual(len(char_capped), 81)
        self.assertEqual(compress_module.compress_text(""), "")


class VerifyCoverageTests(unittest.TestCase):
    def test_run_checks_handles_parse_empty_timeout_and_os_error(self) -> None:
        root = Path.cwd()

        parse = verify_module.run_checks(root, ['"'])
        self.assertFalse(parse["ok"])
        self.assertEqual(parse["checks"][0]["returncode"], 2)
        self.assertIn("parse error", parse["checks"][0]["output"])

        empty = verify_module.run_checks(root, ["   "])
        self.assertFalse(empty["ok"])
        self.assertEqual(empty["checks"][0]["output"], "empty check command")

        timeout = subprocess.TimeoutExpired(cmd=["tool"], timeout=120)
        with patch("ai_workflow.verify.subprocess.run", side_effect=timeout):
            result = verify_module.run_checks(root, ["tool"])
        self.assertEqual(result["checks"][0]["returncode"], 124)

        with patch("ai_workflow.verify.subprocess.run", side_effect=OSError("missing")):
            result = verify_module.run_checks(root, ["missing-tool"])
        self.assertEqual(result["checks"][0]["returncode"], 124)

    def test_windows_command_split_and_handoff_failure(self) -> None:
        with patch.object(verify_module.os, "name", "nt"):
            self.assertEqual(
                verify_module._split_command('"tool.exe" "hello world"'),
                ["tool.exe", "hello world"],
            )

        with patch("ai_workflow.verify.validate_handoff", return_value=["bad handoff"]):
            result = verify_module.verify(Path.cwd(), [], 20)

        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["handoff_errors"], ["bad handoff"])


class ResearchScoutCoverageTests(unittest.TestCase):
    def paper(self, **changes: object) -> research_scout.Paper:
        data: dict[str, object] = {
            "arxiv_id": "2609.12345",
            "title": "Repository Retrieval for Coding Agents",
            "summary": "Agentic repository retrieval improves token efficiency.",
            "authors": ("A. Researcher", "B. Researcher"),
            "categories": ("cs.SE", "cs.IR"),
            "published": "2026-09-15T00:00:00Z",
            "updated": "2026-09-15T01:00:00Z",
            "doi": None,
            "url": "https://arxiv.org/abs/2609.12345",
        }
        data.update(changes)
        return research_scout.Paper(**data)

    def test_url_validation_accepts_only_trusted_https_endpoints(self) -> None:
        good = "https://export.arxiv.org/api/query"
        self.assertEqual(research_scout._validated_research_url(good), good)

        bad_urls = (
            "http://export.arxiv.org/api/query",
            "https://example.com/api",
            "https://user@export.arxiv.org/api/query",
            "https://export.arxiv.org:444/api/query",
            "https://export.arxiv.org:bad/api/query",
        )
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                research_scout._validated_research_url(url)

    def test_request_enforces_response_limit_without_network(self) -> None:
        class Response:
            def __init__(self, payload: bytes):
                self.payload = payload

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                return self.payload

        class Opener:
            def __init__(self, payload: bytes):
                self.payload = payload

            def open(self, *_args: object, **_kwargs: object) -> Response:
                return Response(self.payload)

        with (
            patch.object(research_scout, "MAX_RESEARCH_RESPONSE_BYTES", 4),
            patch(
                "ai_workflow.research_scout.urllib.request.build_opener",
                return_value=Opener(b"1234"),
            ),
        ):
            self.assertEqual(
                research_scout._request("https://export.arxiv.org/api/query"),
                b"1234",
            )

        with (
            patch.object(research_scout, "MAX_RESEARCH_RESPONSE_BYTES", 4),
            patch(
                "ai_workflow.research_scout.urllib.request.build_opener",
                return_value=Opener(b"12345"),
            ),
            self.assertRaisesRegex(ValueError, "exceeded"),
        ):
            research_scout._request("https://export.arxiv.org/api/query")

    def test_xml_clean_similarity_and_scoring_helpers(self) -> None:
        root = research_scout._parse_arxiv_xml(b"<feed><entry /></feed>")
        self.assertEqual(root.tag, "feed")
        for raw in (
            b"<!DOCTYPE foo><feed />",
            b"<!ENTITY x 'y'><feed />",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                research_scout._parse_arxiv_xml(raw)

        self.assertEqual(research_scout._clean(" a\n b "), "a b")
        self.assertEqual(research_scout.title_similarity("", "x"), 0.0)
        self.assertEqual(
            research_scout.title_similarity("Code-Agent Retrieval", "code agent retrieval"),
            1.0,
        )
        self.assertGreater(research_scout.score_paper(self.paper()), 5)

    def test_arxiv_query_and_fetch_parser(self) -> None:
        query = research_scout._arxiv_query(0, 3)
        self.assertTrue(query.startswith(research_scout.ARXIV_API + "?"))
        self.assertIn("max_results=3", query)

        raw = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/2609.12345v2</id>
            <title> Repository Retrieval </title>
            <summary> Useful evidence </summary>
            <published>2026-09-15T00:00:00Z</published>
            <updated>2026-09-15T01:00:00Z</updated>
            <author><name>A. Researcher</name></author>
            <category term="cs.SE"/>
            <arxiv:doi>10.1000/example</arxiv:doi>
            <link rel="alternate" href="https://arxiv.org/abs/2609.12345"/>
          </entry>
        </feed>"""
        with patch("ai_workflow.research_scout._request", return_value=raw):
            papers = research_scout.fetch_arxiv(days=1, max_results=3)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].arxiv_id, "2609.12345")
        self.assertEqual(papers[0].authors, ("A. Researcher",))
        self.assertEqual(papers[0].doi, "10.1000/example")

    def test_crossref_corroboration_success_and_fail_open(self) -> None:
        paper = self.paper()
        payload = {
            "message": {
                "items": [
                    {
                        "title": [paper.title],
                        "URL": "https://doi.org/10.1000/example",
                        "DOI": "10.1000/example",
                    }
                ]
            }
        }
        with patch(
            "ai_workflow.research_scout._request",
            return_value=json.dumps(payload).encode("utf-8"),
        ):
            verified = research_scout.corroborate_crossref(paper)
        self.assertEqual(verified.verification, "arxiv+crossref")
        self.assertEqual(verified.doi, "10.1000/example")

        with patch("ai_workflow.research_scout._request", side_effect=OSError("offline")):
            self.assertEqual(research_scout.corroborate_crossref(paper), paper)

        with patch(
            "ai_workflow.research_scout._request",
            return_value=b'{"message":{"items":[{"title":[]}]}}',
        ):
            self.assertEqual(research_scout.corroborate_crossref(paper), paper)

    def test_ranking_rendering_run_and_main(self) -> None:
        old = self.paper(updated="2026-09-14T00:00:00Z")
        newer = self.paper(updated="2026-09-16T00:00:00Z")
        irrelevant = self.paper(
            arxiv_id="2609.99999",
            title="Unrelated Topic",
            summary="nothing useful",
            categories=("physics.optics",),
        )
        ranked = research_scout.rank_papers([old, newer, irrelevant], minimum_score=5)
        self.assertEqual(ranked, [newer])

        empty = research_scout.render_markdown([], "2026-09-16T00:00:00+00:00")
        self.assertIn("No new papers", empty)

        rich = self.paper(
            authors=tuple(f"Author {index}" for index in range(8)),
            doi="10.1000/example",
            crossref_url="https://api.crossref.org/works/10.1000/example",
            verification="arxiv+crossref",
        )
        rendered = research_scout.render_markdown([rich], "2026-09-16T00:00:00+00:00")
        self.assertIn("et al.", rendered)
        self.assertIn("Crossref record", rendered)
        self.assertIn("DOI:", rendered)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "latest.md"
            archive = root / "archive"
            with (
                patch("ai_workflow.research_scout.fetch_arxiv", return_value=[newer]),
                patch("ai_workflow.research_scout.corroborate_crossref", return_value=newer),
            ):
                result = research_scout.run(
                    output,
                    archive,
                    days=2,
                    max_results=5,
                    minimum_score=1,
                    limit=2,
                )
            self.assertEqual(result["papers"], 1)
            self.assertTrue(output.is_file())
            self.assertIsNotNone(result["archive"])
            self.assertTrue(Path(str(result["archive"])).is_file())

        with (
            patch.object(
                sys,
                "argv",
                ["ai-workflow-research", "--output", "report.md", "--archive-dir", ""],
            ),
            patch(
                "ai_workflow.research_scout.run",
                return_value={
                    "generated_at": "now",
                    "papers": 0,
                    "output": "report.md",
                    "archive": None,
                    "arxiv_ids": [],
                },
            ) as run,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            research_scout.main()
        self.assertIn('"papers": 0', stdout.getvalue())
        self.assertIsNone(run.call_args.args[1])


class EntryPointCoverageTests(unittest.TestCase):
    def test_entrypoint_version_and_cli_delegation(self) -> None:
        with (
            patch.object(sys, "argv", ["ai-workflow", "--version"]),
            redirect_stdout(io.StringIO()) as stdout,
        ):
            entrypoint.main()
        self.assertTrue(stdout.getvalue().strip())

        with (
            patch.object(sys, "argv", ["ai-workflow", "doctor"]),
            patch("ai_workflow.entrypoint.cli_main") as cli_main,
        ):
            entrypoint.main()
        cli_main.assert_called_once_with()

    def test_easy_setup_parser_and_main(self) -> None:
        parser = easy_setup.build_parser()
        args = parser.parse_args(["--root", "/tmp/project", "--project-name", "Demo"])
        self.assertEqual(args.project_name, "Demo")

        with (
            patch.object(
                sys,
                "argv",
                ["ai-workflow-setup", "--root", "/tmp/project", "--project-name", "Demo"],
            ),
            patch(
                "ai_workflow.easy_setup.setup",
                return_value={"status": "ready"},
            ) as setup,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            easy_setup.main()
        setup.assert_called_once_with(Path("/tmp/project"), "Demo")
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "ready"})

    def test_package_main_module_delegates(self) -> None:
        with patch("ai_workflow.entrypoint.main") as main:
            runpy.run_module("ai_workflow.__main__", run_name="__main__")
        main.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
