import importlib.util
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
        """
    )
    cur.executemany("INSERT INTO tbl_pa_airports(airport_identifier) VALUES (?)", [("KAAA",), ("KDDD",)])
    cur.executemany("INSERT INTO tbl_ea_enroute_waypoints(waypoint_identifier) VALUES (?)", [("AAA",), ("BBB",), ("CCC",), ("DDD",)])
    con.commit()
    con.close()


class RoutesConnectivityCheckTests(unittest.TestCase):
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
