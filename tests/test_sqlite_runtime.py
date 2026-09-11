import unittest

from ai_workflow.sqlite_runtime import (
    parse_sqlite_version,
    require_safe_sqlite_wal_runtime,
    sqlite_wal_runtime_status,
)


class SQLiteRuntimeTests(unittest.TestCase):
    def test_known_vulnerable_and_fixed_versions(self):
        cases = {
            "3.7.0": False,
            "3.44.5": False,
            "3.44.6": True,
            "3.45.3": False,
            "3.50.6": False,
            "3.50.7": True,
            "3.51.2": False,
            "3.51.3": True,
            "3.52.0": False,
            "3.53.0": True,
            "3.53.1": True,
            "4.0.0": True,
        }
        for version, expected in cases.items():
            with self.subTest(version=version):
                self.assertEqual(
                    sqlite_wal_runtime_status(version)["safe_for_wal"],
                    expected,
                )

    def test_withdrawn_352_is_never_accepted_by_numeric_ordering(self):
        status = sqlite_wal_runtime_status("3.52.0")

        self.assertFalse(status["safe_for_wal"])
        self.assertEqual(status["reason"], "withdrawn_sqlite_3_52_0")

    def test_unparseable_version_fails_closed(self):
        status = sqlite_wal_runtime_status("not-a-version")

        self.assertFalse(status["safe_for_wal"])
        self.assertEqual(status["reason"], "unparseable_sqlite_version")

    def test_runtime_requirement_raises_for_affected_version(self):
        with self.assertRaises(RuntimeError):
            require_safe_sqlite_wal_runtime("3.51.2")

    def test_parser_uses_first_three_components(self):
        self.assertEqual(parse_sqlite_version("3.53.1.2"), (3, 53, 1))


if __name__ == "__main__":
    unittest.main()
