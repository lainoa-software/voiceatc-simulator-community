import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The connectivity-check tests already build the mock graph/navdata pair this
# tool has to agree with — reuse them so the fixtures cannot drift apart.
CONNECTIVITY_TESTS = _load(
    "test_routes_connectivity_check", TESTS_DIR / "test_routes_connectivity_check.py"
)
MODULE = _load(
    "routes_airac_migration", REPO_ROOT / "tools" / "routes_airac_migration.py"
)

LAINOA = "LainoaSoftware"
CONTRIBUTOR = "SomeContributor"


class RoutesAiracMigrationTests(unittest.TestCase):
    def _run(
        self,
        root: Path,
        rows: list[str],
        *,
        target_airac: str = "2609",
        with_navdata: bool = True,
        aliases: dict | None = None,
    ) -> tuple[int, list[str], dict]:
        """Run the migration end to end; return (exit_code, output_lines, report)."""
        routes_path = root / "routes.tsv"
        graph_db = root / "graph.s3db"
        navdata_db = root / "navdata.s3db"
        CONNECTIVITY_TESTS.create_graph_db(graph_db)
        CONNECTIVITY_TESTS.create_navdata_db(navdata_db)
        routes_path.write_text(
            "airac 2608\n"
            "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
            + "".join(f"{row}\n" for row in rows),
            encoding="utf-8",
        )

        output_tsv = root / "migration_ready.tsv"
        report_json = root / "migration_report.json"
        argv = [
            "routes_airac_migration.py",
            "--routes", str(routes_path),
            "--graph", str(graph_db),
            "--target-airac", target_airac,
            "--output-tsv", str(output_tsv),
            "--report-json", str(report_json),
        ]
        if with_navdata:
            argv += ["--navdata", str(navdata_db)]
        if aliases is not None:
            alias_path = root / "aliases.json"
            alias_path.write_text(json.dumps(aliases), encoding="utf-8")
            argv += ["--airport-aliases", str(alias_path)]

        with mock.patch.object(sys, "argv", argv):
            exit_code = MODULE.main()

        if exit_code != 0:
            return exit_code, [], {}
        output_lines = output_tsv.read_text(encoding="utf-8").splitlines()
        report = json.loads(report_json.read_text(encoding="utf-8"))
        return exit_code, output_lines, report

    def _assert_route_survives(self, route: str) -> None:
        """A correct route must stay verbatim in migration_ready.tsv."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            row = f"KAAA\tKDDD\t{route}\t2608\t{LAINOA}"
            exit_code, output_lines, report = self._run(Path(tmp_dir), [row])

            self.assertEqual(0, exit_code)
            self.assertEqual(1, report["summary"]["routes_ok"], report["lainoa_routes_to_rebuild"])
            self.assertEqual(0, report["summary"]["lainoa_routes_to_rebuild"])
            self.assertEqual(0, report["summary"]["community_routes_needing_review"])
            self.assertIn(row, output_lines)

    def test_target_cycle_alias_preserves_prior_route_bytes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            row = f"KOLD\tKDDD\tKOLD DCT AAA Y1 CCC DCT KDDD\t2608\t{LAINOA}"
            status, lines, report = self._run(Path(directory), [row], aliases={
                "airac": "2609", "aliases": {"KOLD": {
                    "active_ident": "KAAA", "reason": "same_site_alias", "distance_nm": 0,
                }},
            })
            self.assertEqual(0, status)
            self.assertEqual(1, report["summary"]["routes_ok"])
            self.assertIn(row, lines)

    def test_graph_collapsed_pass_through_fix_is_not_rebuilt(self) -> None:
        """EEE is a pass-through fix the compacted graph bake deleted. The game
        resolves it from navdata, so naming it must not blank the row."""
        self._assert_route_survives("KAAA AAA Y1 EEE Y1 CCC KDDD")

    def test_oceanic_coordinate_fix_is_not_rebuilt(self) -> None:
        """Lat/lon fixes appear in no navdata table and no graph node."""
        self._assert_route_survives("KAAA AAA DCT 59N142W DCT 0330N13300E DCT CCC KDDD")

    def test_cross_fir_airway_hop_is_not_rebuilt(self) -> None:
        """W2 is stored as two icao_code blocks and is absent from the graph;
        get_full_airway concatenates them by seqno, so the hop is flyable."""
        self._assert_route_survives("KAAA AAA W2 DDD KDDD")

    def test_genuinely_broken_lainoa_route_is_blanked(self) -> None:
        """AAA really is not on V2 — this is the case the tool exists for."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            exit_code, output_lines, report = self._run(
                Path(tmp_dir), [f"KAAA\tKDDD\tKAAA CCC V2 AAA KDDD\t2608\t{LAINOA}"]
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(1, report["summary"]["lainoa_routes_to_rebuild"])
            entry = report["lainoa_routes_to_rebuild"][0]
            self.assertEqual("KAAA CCC V2 AAA KDDD", entry["old_route"])
            self.assertEqual(["airway_disconnect"], [e["code"] for e in entry["errors"]])
            self.assertIn("KAAA\tKDDD\t\t\t", output_lines)

    def test_community_route_is_flagged_but_left_intact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            row = f"KAAA\tKDDD\tKAAA CCC V2 AAA KDDD\t2608\t{CONTRIBUTOR}"
            exit_code, output_lines, report = self._run(Path(tmp_dir), [row])

            self.assertEqual(0, exit_code)
            self.assertEqual(0, report["summary"]["lainoa_routes_to_rebuild"])
            self.assertEqual(1, report["summary"]["community_routes_needing_review"])
            self.assertIn(row, output_lines)

    def test_every_row_is_categorised_past_any_findings_cap(self) -> None:
        """validate_routes stops at max_findings; migration must not inherit a cap
        or the untouched tail would be silently categorised 'ok'."""
        broken = [f"KAAA\tKDDD\tKAAA CCC V2 AAA KDDD\t2608\t{LAINOA}"] * 60
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            exit_code, _, report = self._run(Path(tmp_dir), broken)

            self.assertEqual(0, exit_code)
            self.assertEqual(0, report["summary"]["routes_ok"])
            self.assertEqual(60, report["summary"]["lainoa_routes_to_rebuild"])

    def test_header_is_bumped_to_target_airac(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            exit_code, output_lines, report = self._run(
                Path(tmp_dir), [f"KAAA\tKDDD\tKAAA AAA Y1 CCC KDDD\t2608\t{LAINOA}"]
            )

            self.assertEqual(0, exit_code)
            self.assertEqual("airac 2609", output_lines[0])
            self.assertEqual("2608", report["source_airac"])
            self.assertEqual("2609", report["target_airac"])

    def test_refuses_to_run_without_navdata(self) -> None:
        """Without navdata the check falls back to the graph oracle, which would
        blank correct routes — the tool must stop instead."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            exit_code, _, _ = self._run(
                root,
                [f"KAAA\tKDDD\tKAAA AAA Y1 EEE Y1 CCC KDDD\t2608\t{LAINOA}"],
                with_navdata=False,
            )

            self.assertEqual(1, exit_code)
            self.assertFalse((root / "migration_ready.tsv").exists())

    def test_refuses_to_migrate_the_protected_default_airac(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            exit_code, _, _ = self._run(
                root,
                [f"KAAA\tKDDD\tKAAA AAA Y1 CCC KDDD\t2608\t{LAINOA}"],
                target_airac=str(MODULE._PROTECTED_AIRAC_MAX),
            )

            self.assertEqual(1, exit_code)
            self.assertFalse((root / "migration_ready.tsv").exists())


if __name__ == "__main__":
    unittest.main()
