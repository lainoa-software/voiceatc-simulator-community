import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "routes_connectivity_check.py"
SPEC = importlib.util.spec_from_file_location("routes_connectivity_check", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def create_graph_db(path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE nodes (
            node_id INTEGER PRIMARY KEY,
            ident TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            is_airway_endpoint INTEGER NOT NULL,
            is_airway_intersection INTEGER NOT NULL,
            is_fra_entry INTEGER NOT NULL,
            is_fra_exit INTEGER NOT NULL,
            is_fra_ex INTEGER NOT NULL,
            airway_count INTEGER NOT NULL,
            in_degree INTEGER NOT NULL,
            out_degree INTEGER NOT NULL
        );
        CREATE TABLE airway_edges (
            edge_id INTEGER PRIMARY KEY,
            from_node_id INTEGER NOT NULL,
            to_node_id INTEGER NOT NULL,
            airway_ident TEXT NOT NULL,
            airway_postfix TEXT,
            link_kind TEXT NOT NULL,
            route_type TEXT,
            flight_level TEXT,
            distance_nm REAL NOT NULL,
            has_shape INTEGER NOT NULL
        );
        CREATE TABLE fra_dct_edges (
            from_node_id INTEGER NOT NULL,
            to_node_id INTEGER NOT NULL,
            distance_nm REAL NOT NULL,
            PRIMARY KEY (from_node_id, to_node_id)
        ) WITHOUT ROWID;
        """
    )
    cur.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '7')")
    cur.executemany(
        """
        INSERT INTO nodes(
            node_id, ident, latitude, longitude,
            is_airway_endpoint, is_airway_intersection, is_fra_entry, is_fra_exit, is_fra_ex,
            airway_count, in_degree, out_degree
        ) VALUES (?, ?, ?, ?, 0, 1, 0, 0, 0, 1, 1, 1)
        """,
        [
            (1, "AAA", 0.0, 0.0),
            (2, "BBB", 0.0, 1.0),
            (3, "CCC", 0.0, 2.0),
            (4, "DDD", 0.0, 3.0),
        ],
    )
    cur.executemany(
        """
        INSERT INTO airway_edges(
            edge_id, from_node_id, to_node_id, airway_ident, airway_postfix, link_kind, route_type, flight_level, distance_nm, has_shape
        ) VALUES (?, ?, ?, ?, '', 'sequential', 'R', '', ?, 0)
        """,
        [
            (1, 1, 2, "Y1", 10.0),
            (2, 2, 3, "Y1", 10.0),
            (3, 3, 4, "V2", 10.0),
        ],
    )
    cur.execute("INSERT INTO fra_dct_edges(from_node_id, to_node_id, distance_nm) VALUES (2, 4, 20.0)")
    con.commit()
    con.close()


def create_navdata_db(path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE tbl_pa_airports (
            airport_identifier TEXT NOT NULL
        );
        CREATE TABLE tbl_ea_enroute_waypoints (
            waypoint_identifier TEXT NOT NULL
        );
        CREATE TABLE tbl_d_vhfnavaids (
            navaid_identifier TEXT NOT NULL
        );
        CREATE TABLE tbl_db_enroute_ndbnavaids (
            navaid_identifier TEXT NOT NULL
        );
        CREATE TABLE tbl_er_enroute_airways (
            route_identifier TEXT NOT NULL,
            icao_code TEXT,
            seqno INTEGER NOT NULL,
            waypoint_identifier TEXT NOT NULL
        );
        """
    )
    cur.executemany("INSERT INTO tbl_pa_airports(airport_identifier) VALUES (?)", [("KAAA",), ("KDDD",)])
    cur.executemany("INSERT INTO tbl_ea_enroute_waypoints(waypoint_identifier) VALUES (?)", [("AAA",), ("BBB",), ("CCC",), ("DDD",), ("EEE",)])
    # Y1 runs AAA-EEE-BBB-CCC. EEE is deliberately absent from the compacted
    # graph fixture — it is the pass-through fix the graph bake collapsed, and
    # the only fix here that the graph oracle cannot resolve. W2 is split across
    # two icao_code blocks and is likewise graph-absent, as Navigraph stores any
    # airway that crosses an FIR boundary.
    cur.executemany(
        "INSERT INTO tbl_er_enroute_airways(route_identifier, icao_code, seqno, waypoint_identifier) VALUES (?, ?, ?, ?)",
        [
            ("Y1", "KZ", 10, "AAA"),
            ("Y1", "KZ", 15, "EEE"),
            ("Y1", "KZ", 20, "BBB"),
            ("Y1", "KZ", 30, "CCC"),
            ("W2", "KZ", 10, "AAA"),
            ("W2", "KZ", 20, "BBB"),
            ("W2", "ZY", 30, "CCC"),
            ("W2", "ZY", 40, "DDD"),
            ("V2", "KZ", 10, "CCC"),
            ("V2", "KZ", 20, "DDD"),
        ],
    )
    con.commit()
    con.close()


class RoutesConnectivityCheckTests(unittest.TestCase):
    def test_airport_identifiers_follow_exact_us_and_same_site_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "navdata.s3db"
            create_navdata_db(database)
            with sqlite3.connect(database) as connection:
                connection.execute("ALTER TABLE tbl_pa_airports ADD COLUMN country TEXT")
                connection.executemany("INSERT INTO tbl_pa_airports VALUES (?, ?)", [
                    ("F70", "UNITED STATES"), ("XYZ", "CANADA"),
                    ("KNEW", "UNITED STATES"), ("AAA", "UNITED STATES"),
                ])
            connection.close()
            index = MODULE.NavdataIndex(database, airport_aliases={"KOLD": "KNEW"})
            self.assertTrue(index.has_airport("KF70"))
            self.assertTrue(index.has_airport("KOLD"))
            self.assertTrue(index.has_point("KOLD"))
            self.assertFalse(index.has_airport("KXYZ"))
            self.assertFalse(index.has_airport("EDBW"))
            index.star_airports = {"KNEW", "KAAA", "AAA"}
            index.star_waypoints = {"KNEW": {"FIX"}, "KAAA": {"EXACT"}, "AAA": {"WRONG"}}
            self.assertTrue(index.is_valid_star_entry_point("KOLD", "FIX"))
            self.assertFalse(index.is_valid_star_entry_point("KOLD", "BAD"))
            self.assertTrue(index.is_valid_star_entry_point("KAAA", "EXACT"))
            self.assertFalse(index.is_valid_star_entry_point("KAAA", "WRONG"))

    def test_cycle_alias_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aliases.json"
            manifest = {"airac": "2610", "aliases": {"KOLD": {
                "active_ident": "KNEW", "reason": "same_site_alias", "distance_nm": 0.0,
            }}}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual({"KOLD": "KNEW"}, MODULE.load_airport_aliases(path, "2610"))
            with self.assertRaises(ValueError):
                MODULE.load_airport_aliases(path, "2609")
            manifest["aliases"]["KOLD"]["distance_nm"] = 2.0
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.load_airport_aliases(path, "2610")

    def test_parse_route_tokens_accepts_expected_pattern(self) -> None:
        row = MODULE.RouteRow(12, "KAAA", "KDDD", "KAAA AAA Y1 CCC KDDD", "2602", "Tester")

        point_exists = lambda token: token in {"AAA", "CCC"}
        airway_exists = lambda token: token == "Y1"
        segments, findings = MODULE.parse_route_tokens(row, point_exists=point_exists, airway_exists=airway_exists)

        self.assertEqual(
            [
                MODULE.RouteSegment("KAAA", "", "AAA"),
                MODULE.RouteSegment("AAA", "Y1", "CCC"),
                MODULE.RouteSegment("CCC", "", "KDDD"),
            ],
            segments,
        )
        self.assertEqual([], findings)

    def test_validate_routes_passes_with_airway_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_db(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA Y1 CCC KDDD\t2602\tTester\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertTrue(summary.is_valid)
            self.assertEqual(0, len(summary.errors))

    def test_validate_routes_fails_when_airway_does_not_connect_points(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_db(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA V2 CCC KDDD\t2602\tTester\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertFalse(summary.is_valid)
            self.assertEqual("airway_disconnect", summary.errors[0].code)

    def _validate(self, root: Path, route: str, *, with_graph: bool = True) -> object:
        routes_path = root / "routes.tsv"
        graph_db = root / "graph.s3db"
        navdata_db = root / "navdata.s3db"
        create_graph_db(graph_db)
        create_navdata_db(navdata_db)
        routes_path.write_text(
            "airac 2602\n"
            "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
            f"{route}\t2602\tTester\n",
            encoding="utf-8",
        )
        return MODULE.validate_routes(
            routes_path,
            graph_db if with_graph else None,
            navdata_db,
            strict_dct=False,
            max_findings=100,
        )

    def test_fix_collapsed_out_of_graph_still_validates(self) -> None:
        """EEE is a pass-through fix the compacted graph bake deleted; the game
        resolves it from navdata, so naming it must not fail the route."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA Y1 EEE Y1 CCC KDDD")
            self.assertEqual([], [finding.code for finding in summary.errors])

    def test_airway_split_across_fir_blocks_validates(self) -> None:
        """W2 is stored as two icao_code blocks; get_full_airway concatenates them
        by seqno with no airspace filter, so a crossing hop is flyable."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA W2 DDD KDDD")
            self.assertEqual([], [finding.code for finding in summary.errors])

    def test_coordinate_fix_is_a_known_point(self) -> None:
        """Oceanic lat/lon fixes are in neither database but are valid points."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA DCT 59N142W DCT 0330N13300E DCT CCC KDDD")
            self.assertEqual([], [finding.code for finding in summary.errors])

    def test_fix_genuinely_off_the_airway_still_fails(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA CCC V2 AAA KDDD")
            self.assertEqual(["airway_disconnect"], [finding.code for finding in summary.errors])
            self.assertIn("AAA not on airway V2", summary.errors[0].detail)

    def test_unknown_token_names_the_point_not_the_airway(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA Y1 ZZZZZ KDDD")
            self.assertEqual(["point_missing"], [finding.code for finding in summary.errors])
            self.assertIn("point ZZZZZ", summary.errors[0].detail)
            self.assertNotIn("Y1", summary.errors[0].detail)

    def test_all_faults_reported_not_just_the_first(self) -> None:
        """A bad token used to abandon the whole route, hiding later mistakes."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA DCT ZZZZZ DCT CCC V2 AAA KDDD")
            self.assertEqual({"point_missing", "airway_disconnect"}, {finding.code for finding in summary.errors})

    def test_validates_without_a_compacted_graph(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            summary = self._validate(Path(tmp_dir), "KAAA\tKDDD\tKAAA AAA Y1 CCC KDDD", with_graph=False)
            self.assertTrue(summary.is_valid)
            self.assertIsNone(summary.graph_db)

    def test_validate_routes_warns_for_unchecked_dct_by_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_db(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA DCT CCC KDDD\t2602\tTester\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertTrue(summary.is_valid)
            self.assertEqual("dct_unchecked", summary.warnings[0].code)


if __name__ == "__main__":
    unittest.main()
