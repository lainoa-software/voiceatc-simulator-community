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
            (2, "GOOD_ENTRY", 0.0, 1.0),
            (3, "WRONG_FIX", 0.0, 2.0),
            (4, "MID_STAR", 0.0, 3.0),
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
            (2, 1, 3, "Y1", 10.0),
            (3, 1, 4, "Y1", 10.0),
        ],
    )
    con.commit()
    con.close()


def create_navdata_with_stars(path: Path) -> None:
    """Navdata that includes tbl_pe_stars — GOOD_ENTRY is valid for KDDD, WRONG_FIX is not."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE tbl_pa_airports (airport_identifier TEXT NOT NULL);
        CREATE TABLE tbl_ea_enroute_waypoints (waypoint_identifier TEXT NOT NULL);
        CREATE TABLE tbl_d_vhfnavaids (navaid_identifier TEXT NOT NULL);
        CREATE TABLE tbl_db_enroute_ndbnavaids (navaid_identifier TEXT NOT NULL);
        CREATE TABLE tbl_pe_stars (
            airport_identifier TEXT NOT NULL,
            procedure_identifier TEXT NOT NULL,
            transition_identifier TEXT NOT NULL,
            route_type TEXT NOT NULL,
            seqno INTEGER NOT NULL,
            waypoint_identifier TEXT NOT NULL
        );
        """
    )
    cur.executemany("INSERT INTO tbl_pa_airports VALUES (?)", [("KAAA",), ("KDDD",)])
    cur.executemany("INSERT INTO tbl_ea_enroute_waypoints VALUES (?)", [("AAA",), ("GOOD_ENTRY",), ("MID_STAR",), ("WRONG_FIX",)])
    cur.executemany(
        "INSERT INTO tbl_pe_stars(airport_identifier, procedure_identifier, transition_identifier, route_type, seqno, waypoint_identifier) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("KDDD", "P1", "E1", "1", 10, "GOOD_ENTRY"),
            ("KDDD", "P1", "E1", "1", 20, "MID_STAR"),
        ],
    )
    con.commit()
    con.close()


def create_navdata_without_stars(path: Path) -> None:
    """Navdata that does NOT include tbl_pe_stars — STAR check must be skipped."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE tbl_pa_airports (airport_identifier TEXT NOT NULL);
        CREATE TABLE tbl_ea_enroute_waypoints (waypoint_identifier TEXT NOT NULL);
        CREATE TABLE tbl_d_vhfnavaids (navaid_identifier TEXT NOT NULL);
        CREATE TABLE tbl_db_enroute_ndbnavaids (navaid_identifier TEXT NOT NULL);
        """
    )
    cur.executemany("INSERT INTO tbl_pa_airports VALUES (?)", [("KAAA",), ("KDDD",)])
    cur.executemany("INSERT INTO tbl_ea_enroute_waypoints VALUES (?)", [("AAA",), ("GOOD_ENTRY",), ("MID_STAR",), ("WRONG_FIX",)])
    con.commit()
    con.close()


class StarEntryValidationTests(unittest.TestCase):

    def test_valid_star_entry_passes(self) -> None:
        """Route ending with a published STAR entry for the destination must pass."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_with_stars(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA Y1 GOOD_ENTRY KDDD\t2602\tLainoaSoftware\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertTrue(summary.is_valid)
            codes = [e.code for e in summary.errors]
            self.assertNotIn("star_entry_not_in_procedure", codes)

    def test_invalid_star_entry_fails(self) -> None:
        """Route ending with a fix that is NOT in tbl_pe_stars for the dest must fail."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_with_stars(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA Y1 WRONG_FIX KDDD\t2602\tLainoaSoftware\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertFalse(summary.is_valid)
            self.assertEqual("star_entry_not_in_procedure", summary.errors[0].code)

    def test_mid_star_fix_fails_as_entry(self) -> None:
        """Route ending with a fix that is in the STAR but NOT at the entry point must fail."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_with_stars(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA Y1 MID_STAR KDDD\t2602\tLainoaSoftware\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertFalse(summary.is_valid)
            self.assertEqual("star_entry_not_in_procedure", summary.errors[0].code)
            self.assertIn("is not a published STAR entry point", summary.errors[0].detail)

    def test_check_skipped_without_star_table(self) -> None:
        """When tbl_pe_stars is absent from navdata, no STAR check runs — no false failure."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "routes.tsv"
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_without_stars(navdata_db)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "KAAA\tKDDD\tKAAA AAA Y1 WRONG_FIX KDDD\t2602\tLainoaSoftware\n",
                encoding="utf-8",
            )

            summary = MODULE.validate_routes(routes_path, graph_db, navdata_db, strict_dct=False, max_findings=10)

            self.assertTrue(summary.is_valid)
            codes = [e.code for e in summary.errors]
            self.assertNotIn("star_entry_not_in_procedure", codes)


if __name__ == "__main__":
    unittest.main()
