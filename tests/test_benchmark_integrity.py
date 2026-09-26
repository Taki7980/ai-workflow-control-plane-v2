from __future__ import annotations

import copy
import unittest

from ai_workflow.benchmark_integrity import (
    analyze_partition_integrity,
    canonical_document_sha256,
)


def positive_case(
    case_id: str,
    repository_id: str,
    *,
    task: str = "Where is request validation handled?",
    commit: str = "a" * 40,
    manifest: str = "b" * 64,
) -> dict:
    return {
        "schema_version": 2,
        "case_id": case_id,
        "task": task,
        "task_type": "comment2context",
        "control_type": "positive",
        "repository_id": repository_id,
        "repository_path": ".",
        "base_commit": commit,
        "content_manifest_sha256": manifest,
        "gold_files": ["src/auth.py"],
        "gold_spans": [
            {
                "repository_id": repository_id,
                "path": "src/auth.py",
                "start_line": 10,
                "end_line": 20,
            }
        ],
        "language": "python",
        "label_source": "human_and_verified_patch",
        "labeler_count": 2,
        "budget_tokens": 8192,
        "budget_lines": 400,
        "source_event_time": "2026-01-01T00:00:00Z",
    }


def document(corpus_id: str, split: str, cases: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "corpus_id": corpus_id,
        "source": {
            "name": "test-source",
            "url": "https://example.test/source",
            "license": "test-only",
        },
        "split": split,
        "cases": cases,
    }


def clean_partitions() -> list[dict]:
    return [
        document(
            "development-corpus",
            "development",
            [
                positive_case(
                    "dev-1",
                    "org/repo-dev",
                    task="Where is request validation handled?",
                    commit="1" * 40,
                    manifest="2" * 64,
                )
            ],
        ),
        document(
            "calibration-corpus",
            "calibration",
            [
                positive_case(
                    "cal-1",
                    "org/repo-cal",
                    task="How is retry backoff calculated?",
                    commit="3" * 40,
                    manifest="4" * 64,
                )
            ],
        ),
        document(
            "holdout-corpus",
            "holdout",
            [
                positive_case(
                    "hold-1",
                    "org/repo-hold",
                    task="Which module owns cache invalidation?",
                    commit="5" * 40,
                    manifest="6" * 64,
                )
            ],
        ),
    ]


class BenchmarkIntegrityTests(unittest.TestCase):
    def test_clean_repository_disjoint_partitions_are_ready(self) -> None:
        report = analyze_partition_integrity(clean_partitions())

        self.assertTrue(report["ready"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["cases"], 3)
        self.assertEqual(
            report["repositories_by_split"]["holdout"],
            ["org/repo-hold"],
        )
        self.assertTrue(
            all(
                len(row["document_sha256"]) == 64
                for row in report["corpora"]
            )
        )

    def test_repository_overlap_between_protected_splits_blocks(self) -> None:
        documents = clean_partitions()
        documents[2]["cases"][0]["repository_id"] = "org/repo-dev"
        documents[2]["cases"][0]["gold_spans"][0][
            "repository_id"
        ] = "org/repo-dev"

        report = analyze_partition_integrity(documents)

        self.assertFalse(report["ready"])
        self.assertIn(
            "cross_split_repository_overlap",
            {item["code"] for item in report["blockers"]},
        )

    def test_normalized_task_duplicate_across_splits_blocks(self) -> None:
        documents = clean_partitions()
        documents[2]["cases"][0]["task"] = (
            "  WHERE   is request validation handled??? "
        )

        report = analyze_partition_integrity(documents)

        self.assertFalse(report["ready"])
        self.assertIn(
            "cross_split_task_duplicate",
            {item["code"] for item in report["blockers"]},
        )

    def test_source_instance_duplicate_across_splits_blocks(self) -> None:
        documents = clean_partitions()
        copied = copy.deepcopy(documents[0]["cases"][0])
        copied["case_id"] = "hold-copy"
        copied["task"] = "Explain request validation in this snapshot"
        documents[2]["cases"][0] = copied

        report = analyze_partition_integrity(documents)

        self.assertFalse(report["ready"])
        self.assertIn(
            "cross_split_source_instance_duplicate",
            {item["code"] for item in report["blockers"]},
        )

    def test_duplicate_case_id_blocks_even_with_different_source(self) -> None:
        documents = clean_partitions()
        documents[2]["cases"][0]["case_id"] = "dev-1"

        report = analyze_partition_integrity(documents)

        self.assertIn(
            "duplicate_case_id",
            {item["code"] for item in report["blockers"]},
        )

    def test_gold_and_repository_hints_are_reported_not_hidden(self) -> None:
        documents = clean_partitions()
        documents[2]["cases"][0]["task"] = (
            "In org/repo-hold, inspect src/auth.py and explain validation."
        )

        report = analyze_partition_integrity(documents)
        codes = {item["code"] for item in report["leakage_signals"]}

        self.assertIn("gold_path_exposed_in_task", codes)
        self.assertIn("repository_identity_exposed_in_task", codes)

    def test_missing_temporal_provenance_is_visible_signal(self) -> None:
        documents = clean_partitions()
        del documents[2]["cases"][0]["source_event_time"]

        report = analyze_partition_integrity(documents)

        self.assertIn(
            "missing_temporal_provenance",
            {item["code"] for item in report["leakage_signals"]},
        )

    def test_invalid_temporal_provenance_blocks(self) -> None:
        documents = clean_partitions()
        documents[1]["cases"][0]["source_event_time"] = "not-a-date"

        report = analyze_partition_integrity(documents)

        self.assertFalse(report["ready"])
        self.assertIn(
            "invalid_temporal_provenance",
            {item["code"] for item in report["blockers"]},
        )

    def test_document_digest_is_canonical(self) -> None:
        value = clean_partitions()[0]
        same = {
            "cases": value["cases"],
            "split": value["split"],
            "source": value["source"],
            "corpus_id": value["corpus_id"],
            "schema_version": value["schema_version"],
        }

        self.assertEqual(
            canonical_document_sha256(value),
            canonical_document_sha256(same),
        )


if __name__ == "__main__":
    unittest.main()
