import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_python_reproducibility import (
    compare_distribution_directories,
)


class PythonDistributionReproducibilityTests(unittest.TestCase):
    def _write_dist(
        self,
        root: Path,
        *,
        wheel: bytes = b"wheel-bytes",
        sdist: bytes = b"sdist-bytes",
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "ai_workflow_control_plane-2.3.0-py3-none-any.whl").write_bytes(
            wheel
        )
        (root / "ai_workflow_control_plane-2.3.0.tar.gz").write_bytes(sdist)

    def test_identical_distributions_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second)

            report = compare_distribution_directories(
                first,
                second,
                source_date_epoch=1_700_000_000,
            )

        self.assertTrue(report["reproducible"])
        self.assertEqual(report["artifact_count"], 2)
        self.assertEqual(report["digest_mismatches"], [])
        self.assertEqual(report["only_candidate_a"], [])
        self.assertEqual(report["only_candidate_b"], [])
        self.assertTrue(all(row["match"] for row in report["artifacts"]))
        json.dumps(report)

    def test_changed_bytes_fail_reproducibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second, wheel=b"different-wheel")

            report = compare_distribution_directories(
                first,
                second,
                source_date_epoch=1,
            )

        self.assertFalse(report["reproducible"])
        self.assertEqual(
            report["digest_mismatches"],
            ["ai_workflow_control_plane-2.3.0-py3-none-any.whl"],
        )

    def test_missing_artifact_fails_reproducibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second)
            (
                second / "ai_workflow_control_plane-2.3.0.tar.gz"
            ).unlink()

            with self.assertRaisesRegex(
                ValueError,
                "must contain an sdist",
            ):
                compare_distribution_directories(
                    first,
                    second,
                    source_date_epoch=1,
                )

    def test_unexpected_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second)
            (first / "debug.log").write_text("unexpected", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "unexpected file",
            ):
                compare_distribution_directories(
                    first,
                    second,
                    source_date_epoch=1,
                )

    def test_symlink_artifacts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second)
            target = first / "real.whl"
            target.write_bytes(b"x")
            link = first / "linked.whl"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            with self.assertRaisesRegex(
                ValueError,
                "must not be a symlink",
            ):
                compare_distribution_directories(
                    first,
                    second,
                    source_date_epoch=1,
                )

    def test_negative_source_date_epoch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = root / "a"
            second = root / "b"
            self._write_dist(first)
            self._write_dist(second)

            with self.assertRaisesRegex(
                ValueError,
                "must be non-negative",
            ):
                compare_distribution_directories(
                    first,
                    second,
                    source_date_epoch=-1,
                )


if __name__ == "__main__":
    unittest.main()
