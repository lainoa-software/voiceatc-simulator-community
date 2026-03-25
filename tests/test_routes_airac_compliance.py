import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "routes_airac_compliance.py"
SPEC = importlib.util.spec_from_file_location("routes_airac_compliance", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RoutesAiracComplianceTests(unittest.TestCase):
    def test_active_airac_cycle_matches_known_2026_dates(self) -> None:
        cycle = MODULE.active_airac_cycle(date(2026, 3, 20))

        self.assertEqual("2603", cycle.code)
        self.assertEqual(date(2026, 3, 19), cycle.effective_date)
        self.assertEqual(date(2026, 4, 16), cycle.next_effective_date)

    def test_validate_routes_file_passes_when_declared_airac_matches_active_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            routes_path = Path(tmp_dir) / "routes.tsv"
            routes_path.write_text(
                "airac 2603\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\t2603\tTester\n",
                encoding="utf-8",
            )

            result = MODULE.validate_routes_file(routes_path, date(2026, 3, 20))

            self.assertTrue(result.is_compliant)
            self.assertEqual(0, result.older_creation_count)

    def test_validate_routes_file_fails_when_declared_airac_is_outdated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            routes_path = Path(tmp_dir) / "routes.tsv"
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\t2602\tTester\n",
                encoding="utf-8",
            )

            result = MODULE.validate_routes_file(routes_path, date(2026, 3, 20))

            self.assertFalse(result.is_compliant)
            self.assertEqual("2603", result.active_cycle.code)

    def test_validate_routes_file_fails_when_creation_airac_is_newer_than_file_airac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            routes_path = Path(tmp_dir) / "routes.tsv"
            routes_path.write_text(
                "airac 2603\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\t2604\tTester\n",
                encoding="utf-8",
            )

            result = MODULE.validate_routes_file(routes_path, date(2026, 3, 20))

            self.assertFalse(result.is_compliant)
            self.assertEqual(("2604",), result.newer_creation_airacs)


if __name__ == "__main__":
    unittest.main()
