import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "player_routes_manifest.py"
SPEC = importlib.util.spec_from_file_location("player_routes_manifest", MODULE_PATH)
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
        ],
    )
    con.commit()
    con.close()


def create_navdata_db(path: Path) -> None:
    """Minimal navdata: deep validation is decided against this, not the graph."""
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE tbl_pa_airports (airport_identifier TEXT NOT NULL);
        CREATE TABLE tbl_ea_enroute_waypoints (waypoint_identifier TEXT NOT NULL);
        CREATE TABLE tbl_er_enroute_airways (
            route_identifier TEXT NOT NULL,
            icao_code TEXT,
            seqno INTEGER NOT NULL,
            waypoint_identifier TEXT NOT NULL
        );
        """
    )
    cur.executemany("INSERT INTO tbl_pa_airports(airport_identifier) VALUES (?)", [("KAAA",), ("KDDD",)])
    cur.executemany(
        "INSERT INTO tbl_ea_enroute_waypoints(waypoint_identifier) VALUES (?)",
        [("AAA",), ("BBB",), ("CCC",)],
    )
    cur.executemany(
        "INSERT INTO tbl_er_enroute_airways(route_identifier, icao_code, seqno, waypoint_identifier) VALUES (?, ?, ?, ?)",
        [("Y1", "KZ", 10, "AAA"), ("Y1", "KZ", 20, "BBB"), ("Y1", "KZ", 30, "CCC")],
    )
    con.commit()
    con.close()


def make_route_entry(origin: str, dest: str, middle: str) -> dict:
    route = MODULE.normalize_route(f"{origin} DCT {middle} DCT {dest}" if middle else f"{origin} DCT {dest}")
    return {
        "id": MODULE.route_id_for(route),
        "route": route,
        "created_at": "2026-08-08T12:00:00Z",
        "creation_airac": "2607",
    }


def write_player_file(root: Path, lane: str, origin: str, dest: str, routes: list[dict]) -> Path:
    target = root / "ROUTES" / "player" / lane / origin[:2] / f"{origin}_{dest}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 2, "origin": origin, "dest": dest, "routes": routes}
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def write_lane_headers(root: Path, current_airac: str = "2607", default_airac: str = "2503") -> None:
    routes_dir = root / "ROUTES"
    routes_dir.mkdir(parents=True, exist_ok=True)
    (routes_dir / "routes.tsv").write_text(
        f"airac {current_airac}\n{MODULE.TSV_COLUMN_HEADER}\n", encoding="utf-8"
    )
    (routes_dir / "routes_default.tsv").write_text(
        f"airac {default_airac}\n{MODULE.TSV_COLUMN_HEADER}\n", encoding="utf-8"
    )


class PlayerRoutesManifestTests(unittest.TestCase):
    def test_route_id_matches_normalized_hash(self) -> None:
        self.assertEqual(
            MODULE.route_id_for("lemh dct  mameb dct lepa"),
            MODULE.route_id_for("LEMH DCT MAMEB DCT LEPA"),
        )
        self.assertRegex(MODULE.route_id_for("LEMH DCT LEPA"), r"^[0-9a-f]{8}$")

    def test_load_lane_accepts_valid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_player_file(root, "current", "LEMH", "LEPA", [make_route_entry("LEMH", "LEPA", "MAMEB")])
            rows = MODULE.load_lane("current", root)
        self.assertEqual(1, len(rows))
        self.assertEqual("LEMH_LEPA", rows[0].pair_key)
        self.assertEqual("current", rows[0].lane)

    def test_load_lane_rejects_contract_violations(self) -> None:
        base_entry = make_route_entry("LEMH", "LEPA", "MAMEB")
        cases = [
            ("wrong id", {**base_entry, "id": "deadbeef"}),
            ("missing bookends", {**base_entry, "id": MODULE.route_id_for("LEMH MAMEB LEPA"), "route": "LEMH MAMEB LEPA"}),
            ("public author field", {**base_entry, "author": "Test Pilot"}),
            (
                "runway token",
                {
                    **base_entry,
                    "id": MODULE.route_id_for("LEMH DCT RW06L DCT LEPA"),
                    "route": "LEMH DCT RW06L DCT LEPA",
                },
            ),
            (
                "illegal charset",
                {
                    **base_entry,
                    "id": MODULE.route_id_for("LEMH DCT MA_EB DCT LEPA"),
                    "route": "LEMH DCT MA_EB DCT LEPA",
                },
            ),
        ]
        for label, entry in cases:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    write_player_file(root, "current", "LEMH", "LEPA", [entry])
                    with self.assertRaises(ValueError):
                        MODULE.load_lane("current", root)

    def test_load_lane_rejects_wrong_placement_and_caps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ROUTES" / "player" / "current" / "XX" / "LEMH_LEPA.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": 2,
                "origin": "LEMH",
                "dest": "LEPA",
                "routes": [make_route_entry("LEMH", "LEPA", "MAMEB")],
            }
            target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.load_lane("current", root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            variants = [
                make_route_entry("LEMH", "LEPA", f"FIX{index}")
                for index in range(MODULE.MAX_VARIANTS_PER_PAIR + 1)
            ]
            write_player_file(root, "current", "LEMH", "LEPA", variants)
            with self.assertRaises(ValueError):
                MODULE.load_lane("current", root)

    def test_load_lane_tolerates_empty_routes_array(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_player_file(root, "current", "LEMH", "LEPA", [])
            self.assertEqual([], MODULE.load_lane("current", root))

    def test_validate_tree_reports_every_bad_file(self) -> None:
        """One stale publish breaks many files at once; reporting them one per
        run costs the contributor a round trip per file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_player_file(root, "current", "LEMH", "LEPA", [make_route_entry("LEMH", "LEPA", "MAMEB")])
            legacy = write_player_file(root, "current", "LEMD", "LEBL", [make_route_entry("LEMD", "LEBL", "PINAR")])
            legacy.write_text(legacy.read_text(encoding="utf-8").replace('"schema_version": 2', '"schema_version": 1'), encoding="utf-8")
            named = make_route_entry("LEZL", "LEVC", "TERSA")
            write_player_file(root, "current", "LEZL", "LEVC", [{**named, "author": "Test Pilot"}])

            with self.assertRaises(ValueError) as caught:
                MODULE.validate_tree(root)

        message = str(caught.exception)
        self.assertIn("2 player route file(s) failed validation:", message)
        self.assertIn("LEMD_LEBL.json: schema_version must be 2", message)
        self.assertIn("LEZL_LEVC.json: routes[0].author is not allowed", message)
        self.assertNotIn("LEMH_LEPA.json", message)

    def test_deep_validate_flags_unknown_token_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_db(navdata_db)
            good = make_route_entry("KAAA", "KDDD", "AAA Y1 CCC")
            bad = make_route_entry("KAAA", "KDDD", "ZZZZ")
            write_player_file(root, "current", "KAAA", "KDDD", [good, bad])
            rows = MODULE.load_lane("current", root)
            deprecated = MODULE.deep_validate_lane(rows, graph_db, navdata_db)
        self.assertIsNotNone(deprecated)
        self.assertNotIn(good["id"], deprecated)
        self.assertIn(bad["id"], deprecated)
        self.assertTrue(any(reason.startswith("point_missing:") for reason in deprecated[bad["id"]]))

    def test_deep_validate_without_navdata_returns_none(self) -> None:
        """Navdata decides acceptance, so its absence must carry status forward
        rather than silently fall back to the compacted graph."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_db = root / "graph.s3db"
            create_graph_db(graph_db)
            self.assertIsNone(MODULE.deep_validate_lane([], None, None))
            self.assertIsNone(MODULE.deep_validate_lane([], graph_db, None))
            self.assertIsNone(MODULE.deep_validate_lane([], graph_db, Path("missing/navdata.s3db")))

    def test_deep_validate_without_graph_still_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            navdata_db = root / "navdata.s3db"
            create_navdata_db(navdata_db)
            good = make_route_entry("KAAA", "KDDD", "AAA Y1 CCC")
            bad = make_route_entry("KAAA", "KDDD", "ZZZZ")
            write_player_file(root, "current", "KAAA", "KDDD", [good, bad])
            rows = MODULE.load_lane("current", root)
            deprecated = MODULE.deep_validate_lane(rows, None, navdata_db)
        self.assertIsNotNone(deprecated)
        self.assertNotIn(good["id"], deprecated)
        self.assertIn(bad["id"], deprecated)

    def test_lane_status_carry_forward_without_deep_validation(self) -> None:
        entry = make_route_entry("LEMH", "LEPA", "MAMEB")
        fresh = make_route_entry("LEMH", "LEPA", "PTC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_player_file(root, "current", "LEMH", "LEPA", [entry, fresh])
            rows = MODULE.load_lane("current", root)
        previous = {
            "current": {
                "pairs": {
                    "LEMH_LEPA": {
                        entry["id"]: {
                            "status": "deprecated",
                            "checked_airac": "2606",
                            "reasons": ["token_unknown: MAMEB gone"],
                        }
                    }
                }
            }
        }
        lane_status = MODULE.build_lane_status(rows, "current", "2607", None, previous)
        entries = lane_status["pairs"]["LEMH_LEPA"]
        self.assertFalse(lane_status["deep_validation"])
        self.assertEqual("deprecated", entries[entry["id"]]["status"])
        self.assertEqual("2606", entries[entry["id"]]["checked_airac"])
        self.assertEqual("ok", entries[fresh["id"]]["status"])
        self.assertEqual("", entries[fresh["id"]]["checked_airac"])

    def test_overlay_excludes_deprecated_rows(self) -> None:
        good = make_route_entry("LEMH", "LEPA", "MAMEB")
        bad = make_route_entry("LEMH", "LEPA", "PTC")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_player_file(root, "current", "LEMH", "LEPA", [good, bad])
            rows = MODULE.load_lane("current", root)
        lane_status = MODULE.build_lane_status(rows, "current", "2607", {bad["id"]: ["token_unknown: PTC"]}, {})
        overlay_text, route_count = MODULE.build_overlay_tsv(rows, lane_status, "2607")
        lines = overlay_text.splitlines()
        self.assertEqual(1, route_count)
        self.assertEqual("airac 2607", lines[0])
        self.assertEqual(MODULE.TSV_COLUMN_HEADER, lines[1])
        self.assertEqual(3, len(lines))
        self.assertIn(good["route"], lines[2])
        self.assertTrue(lines[2].endswith("\t"))
        self.assertEqual("", lines[2].split("\t")[4])

    def test_build_bundle_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_lane_headers(root)
            graph_db = root / "graph.s3db"
            navdata_db = root / "navdata.s3db"
            create_graph_db(graph_db)
            create_navdata_db(navdata_db)
            good = make_route_entry("KAAA", "KDDD", "AAA Y1 CCC")
            bad = make_route_entry("KAAA", "KDDD", "ZZZZ")
            write_player_file(root, "current", "KAAA", "KDDD", [good, bad])
            write_player_file(root, "default", "KAAA", "KDDD", [make_route_entry("KAAA", "KDDD", "AAA")])
            output_dir = root / "build" / "release"
            summary = MODULE.build_bundle(
                output_dir=output_dir,
                release_tag="daily-2026-08-08",
                published_at="2026-08-08T01:15:00Z",
                commit_sha="abc123",
                download_repo="lainoa-software/voiceatc-simulator-community",
                graph_dbs={"current": graph_db, "default": None},
                navdata_dbs={"current": navdata_db, "default": None},
                root=root,
            )

            manifest = summary["manifests"]["player_routes"]
            status = summary["manifests"]["player_routes_status"]
            current_asset = summary["assets"]["player_routes_tsv"]
            default_asset = summary["assets"]["player_routes_default_tsv"]

            self.assertEqual("2607", manifest["current"]["airac"])
            self.assertEqual("2503", manifest["default"]["airac"])
            self.assertEqual(1, manifest["current"]["route_count"])
            self.assertEqual(1, manifest["default"]["route_count"])
            self.assertIn("player-routes-2607.tsv", manifest["current"]["download_url"])
            self.assertTrue(Path(current_asset["path"]).is_file())
            self.assertTrue(Path(default_asset["path"]).is_file())
            self.assertTrue(status["current"]["deep_validation"])
            self.assertFalse(status["default"]["deep_validation"])
            current_entries = status["current"]["pairs"]["KAAA_KDDD"]
            self.assertEqual("ok", current_entries[good["id"]]["status"])
            self.assertEqual("deprecated", current_entries[bad["id"]]["status"])

            overlay_lines = Path(current_asset["path"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual("airac 2607", overlay_lines[0])
            self.assertEqual(3, len(overlay_lines))

    def test_write_manifests_from_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "player_routes_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "manifests": {
                            "player_routes": {"schema_version": 1},
                            "player_routes_status": {"schema_version": 1},
                        }
                    }
                ),
                encoding="utf-8",
            )
            MODULE.write_manifests_from_summary(summary_path, root)
            manifest_path = root / ".voiceatc" / "player_routes_manifest.json"
            status_path = root / ".voiceatc" / "player_routes_status.json"
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(status_path.is_file())
            self.assertTrue(manifest_path.read_text(encoding="utf-8").endswith("\n"))


if __name__ == "__main__":
    unittest.main()
