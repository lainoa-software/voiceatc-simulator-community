import importlib.util
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "sector_data_manifest.py"
SPEC = importlib.util.spec_from_file_location("sector_data_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


EARTH_RADIUS_NM = 3440.065
KJFK_LATITUDE = 40.6413
KJFK_LONGITUDE = -73.7781
KLGA_LATITUDE = 40.7772
KLGA_LONGITUDE = -73.8726


def polygon_contains(polygon: list[list[float]], latitude: float, longitude: float) -> bool:
    inside = False
    previous_latitude, previous_longitude = polygon[-1]
    for current_latitude, current_longitude in polygon:
        crosses_latitude = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses_latitude:
            crossing_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < crossing_longitude:
                inside = not inside
        previous_latitude = current_latitude
        previous_longitude = current_longitude
    return inside


def great_circle_distance_nm(
    latitude: float,
    longitude: float,
    *,
    origin_latitude: float = KJFK_LATITUDE,
    origin_longitude: float = KJFK_LONGITUDE,
) -> float:
    latitude_1 = math.radians(origin_latitude)
    longitude_1 = math.radians(origin_longitude)
    latitude_2 = math.radians(latitude)
    longitude_2 = math.radians(longitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    haversine = (
        math.sin(delta_latitude / 2.0) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2.0) ** 2
    )
    return EARTH_RADIUS_NM * 2.0 * math.asin(math.sqrt(haversine))


def valid_tma_definitions() -> dict[str, object]:
    return {
        "schema": 3,
        "units": [
            {
                "id": "LEMD_APP",
                "call_sign": "Madrid Approach",
                "services": ["approach_radar"],
            }
        ],
        "positions": [
            {
                "call_sign": "LEMD_APP",
                "unit": "LEMD_APP",
                "frequency": "119.100",
            }
        ],
    }


def valid_tma_layout() -> dict[str, object]:
    return {
        "schema": 3,
        "configurations": {
            "LEMD_APP": {
                "CFG_1": {
                    "positions": {"LEMD_APP": ["LEMDAAA"]},
                    "airports": ["LEMD"],
                    "valid_for_runways": {"LEMD": ["NORTH"]},
                }
            }
        },
    }


def valid_tma_coordination() -> dict[str, object]:
    return {
        "schema": 3,
        "agreements": [
            {
                "name": "LEMD_ARR",
                "from": "LECM_CTR",
                "to": "LEMD_APP",
                "arrives": ["LEMD"],
                "fix": ["ASBIN"],
                "level": "F130",
            }
        ],
    }


def valid_acc_definitions() -> dict[str, object]:
    return {
        "schema": 3,
        "units": [
            {
                "id": "LECM_CTR",
                "call_sign": "Madrid Control",
                "services": ["center"],
            }
        ],
        "positions": [
            {
                "call_sign": "LECM_CTR",
                "unit": "LECM_CTR",
                "frequency": "133.755",
            }
        ],
    }


def valid_sector_definitions() -> dict[str, object]:
    return {
        "schema": 3,
        "sectors": {
            "LEMDAAA": {
                "name": "AAA",
                "title": "Madrid (LEMDAAA)",
            }
        },
        "volumes": [
            {
                "sector_ids": ["LEMDAAA"],
                "lower_limit": 0,
                "higher_limit": 24500,
                "polygon": [[40.0, -3.8], [40.1, -3.7], [40.2, -3.8]],
            }
        ],
    }


class SectorDataManifestTests(unittest.TestCase):
    def test_repository_contains_expected_sector_bundle_paths(self) -> None:
        manifest = MODULE.build_manifest(REPO_ROOT, commit_sha="test-commit")
        core_bundles = {
            "G/GC/GCCC/GCCC_MAIN/CANARIAS_TMA",
            "K/KZNY/JFK_TMA",
            "K/KZNY/LAGUARDIA_TMA",
            "L/LE/LECB/LECP/PALMA_TMA",
            "L/LE/LECB/LECB_W/BARCELONA_TMA",
            "L/LE/LECB/LECL/VALENCIA_TMA",
            "L/LE/LECM/LECM_R1/BILBAO_TMA",
            "L/LE/LECM/LECM_R1/GALICIA_TMA",
            "L/LE/LECM/LECM_R2/MADRID_TMA",
            "L/LE/LECM/LECS/MALAGA_TMA",
            "L/LE/LECM/LECS/SEVILLA_TMA",
        }
        found_bundles = set(manifest["bundles"].keys())
        self.assertTrue(
            core_bundles.issubset(found_bundles),
            f"Missing core sector bundles: {core_bundles - found_bundles}",
        )

    def test_kjfk_bundle_combines_all_playable_jfk_airspace(self) -> None:
        bundle = REPO_ROOT / "K" / "KZNY" / "JFK_TMA"
        definitions = json.loads((bundle / "sector_definitions.json").read_text(encoding="utf-8"))
        tma_layout = json.loads((bundle / "tma_layout.json").read_text(encoding="utf-8"))

        forbidden_metadata = {"source", "provenance", "retrieval", "citation", "licensing"}
        self.assertTrue(forbidden_metadata.isdisjoint(definitions))
        self.assertEqual(3, definitions["schema"])
        self.assertIn("KJFKAPP", definitions["sectors"])

        volumes = definitions["volumes"]
        self.assertEqual(1, len(volumes))
        sector = volumes[0]
        self.assertEqual(["KJFKAPP"], sector["sector_ids"])
        self.assertEqual(0, sector["lower_limit"])
        self.assertEqual(19000, sector["higher_limit"])

        polygon = sector["polygon"]
        self.assertEqual(45, len(polygon))
        self.assertEqual(polygon[0], polygon[-1])
        latitudes = [point[0] for point in polygon]
        longitudes = [point[1] for point in polygon]
        self.assertAlmostEqual(40.033031, min(latitudes), places=6)
        self.assertAlmostEqual(41.003082, max(latitudes), places=6)
        self.assertAlmostEqual(-74.333046, min(longitudes), places=6)
        self.assertAlmostEqual(-72.761970, max(longitudes), places=6)

        maximum_distance_nm = max(
            great_circle_distance_nm(latitude, longitude) for latitude, longitude in polygon
        )
        self.assertGreaterEqual(maximum_distance_nm, 47.5)
        self.assertLessEqual(maximum_distance_nm, 48.5)

        required_volume_samples = {
            "CAMRN_13RL": (40.297022, -73.668013),
            "CAMRN_22RL": (40.284084, -73.841186),
            "CAMRN_31RL": (40.284084, -73.888745),
            "CAMRN_4RL": (40.297022, -73.668013),
            "JFK_DEP_13RL": (40.606491, -73.599588),
            "JFK_DEP_22RL": (40.606491, -73.728324),
            "JFK_DEP_31RL": (40.605333, -73.594744),
            "JFK_DEP_4RL": (40.605333, -73.594724),
            "JFK_FINAL_13RL": (40.531683, -74.080998),
            "JFK_FINAL_22RL": (40.666092, -73.557843),
            "JFK_FINAL_31RL": (40.439880, -73.419786),
            "JFK_FINAL_4RL": (40.462480, -73.912525),
            "JFK_SATELITE_13RL": (40.774351, -73.410729),
            "JFK_SATELITE_22RL": (40.707720, -73.396395),
            "JFK_SATELITE_31RL": (40.754585, -73.399640),
            "JFK_SATELITE_4RL": (40.774351, -73.410729),
            "LENDY_13RL": (40.722431, -73.974851),
            "LENDY_22RL": (40.681906, -73.971396),
            "LENDY_31RL": (40.675983, -73.967143),
            "LENDY_4RL": (40.722431, -73.974851),
            "ROBER_22RL": (40.718605, -73.040139),
            "ROBER_31RL": (40.728580, -73.139448),
            "ROBER_4RL": (40.665029, -73.092999),
        }
        self.assertEqual(23, len(required_volume_samples))
        for volume_name, (latitude, longitude) in required_volume_samples.items():
            self.assertTrue(
                polygon_contains(polygon, latitude, longitude),
                f"Expected {volume_name} sample to be inside the combined JFK envelope",
            )

        influenced_airports = {
            "KJFK": (KJFK_LATITUDE, KJFK_LONGITUDE),
            "KFRG": (40.7288, -73.4134),
        }
        for airport, (latitude, longitude) in influenced_airports.items():
            self.assertTrue(
                polygon_contains(polygon, latitude, longitude),
                f"Expected {airport} to be inside the combined JFK envelope",
            )

        remote_points = {
            "ATHOS": (42.24708, -73.81210),
            "DANZI": (42.17829, -74.95672),
            "PARCH": (41.09923, -72.12074),
            "PAWLN": (41.76986, -73.60073),
            "YODAA": (41.72255, -74.03132),
            "ALB": (42.74728, -73.80318),
            "ENE": (43.42567, -70.61352),
            "SIE": (39.09551, -74.80034),
        }
        for point_name, (latitude, longitude) in remote_points.items():
            self.assertFalse(
                polygon_contains(polygon, latitude, longitude),
                f"Expected {point_name} to remain outside the combined JFK envelope",
            )

        south_arr = tma_layout["configurations"]["KJFK_APP"]["SOUTH_ARR"]
        self.assertEqual(["KJFKAPP"], south_arr["positions"]["KJFK_APP"])
        self.assertEqual({"KJFK", "KFRG"}, set(south_arr["airports"]))

    def test_klga_bundle_uses_simaware_lga_envelope(self) -> None:
        bundle = REPO_ROOT / "K" / "KZNY" / "LAGUARDIA_TMA"
        definitions = json.loads((bundle / "sector_definitions.json").read_text(encoding="utf-8"))
        tma_defs = json.loads((bundle / "tma_definitions.json").read_text(encoding="utf-8"))
        tma_layout = json.loads((bundle / "tma_layout.json").read_text(encoding="utf-8"))
        mva = json.loads((bundle / "mva.json").read_text(encoding="utf-8"))

        forbidden_metadata = {"source", "provenance", "retrieval", "citation", "licensing"}
        self.assertTrue(forbidden_metadata.isdisjoint(definitions))
        self.assertTrue(forbidden_metadata.isdisjoint(mva))
        self.assertEqual(3, definitions["schema"])
        self.assertIn("KLGAAPP", definitions["sectors"])

        volumes = definitions["volumes"]
        self.assertEqual(1, len(volumes))
        sector = volumes[0]
        self.assertEqual(["KLGAAPP"], sector["sector_ids"])
        self.assertEqual(0, sector["lower_limit"])
        self.assertEqual(19000, sector["higher_limit"])

        polygon = sector["polygon"]
        self.assertEqual(65, len(polygon))
        self.assertEqual(polygon[0], polygon[-1])
        latitudes = [point[0] for point in polygon]
        longitudes = [point[1] for point in polygon]
        self.assertAlmostEqual(40.02028, min(latitudes), places=5)
        self.assertAlmostEqual(41.60459, max(latitudes), places=5)
        self.assertAlmostEqual(-75.10694, min(longitudes), places=5)
        self.assertAlmostEqual(-73.27281, max(longitudes), places=5)

        maximum_distance_nm = max(
            great_circle_distance_nm(
                latitude,
                longitude,
                origin_latitude=KLGA_LATITUDE,
                origin_longitude=KLGA_LONGITUDE,
            )
            for latitude, longitude in polygon
        )
        self.assertGreaterEqual(maximum_distance_nm, 57.5)
        self.assertLessEqual(maximum_distance_nm, 58.5)

        self.assertTrue(polygon_contains(polygon, KLGA_LATITUDE, KLGA_LONGITUDE))
        self.assertTrue(polygon_contains(polygon, 41.0669, -73.7076))  # KHPN
        self.assertTrue(polygon_contains(polygon, 41.3715, -73.4822))  # KDXR
        self.assertFalse(polygon_contains(polygon, KJFK_LATITUDE, KJFK_LONGITUDE))

        cfg = tma_layout["configurations"]["KLGA_APP"]["1"]
        self.assertEqual(["KLGAAPP"], cfg["positions"]["KLGA_APP"])
        self.assertEqual("120.800", tma_defs["positions"][0]["frequency"])
        self.assertEqual(["KLGA"], cfg["airports"])

        self.assertEqual("KLGA", mva["airports"][0])
        area_ids = [area["area_id"] for area in mva["mva_areas"]]
        self.assertEqual(len(area_ids), len(set(area_ids)))
        self.assertGreaterEqual(len(area_ids), 15)
        for area in mva["mva_areas"]:
            self.assertGreater(int(area["minimum_altitude_ft"]), 0)
            self.assertGreaterEqual(len(area["polygon"]), 4)
            self.assertEqual(area["polygon"][0], area["polygon"][-1])
            self.assertTrue(area.get("labels"))

    def test_build_manifest_rejects_missing_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "tma_definitions.json").write_text(json.dumps(valid_tma_definitions()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing sector bundle files"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_sector_bundle_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "tma_definitions.json").write_text("{bad json", encoding="utf-8")
            (bundle / "tma_layout.json").write_text(json.dumps(valid_tma_layout()), encoding="utf-8")
            (bundle / "sector_definitions.json").write_text(json.dumps(valid_sector_definitions()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_sector_definitions_rejects_short_polygon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            bad_definitions = valid_sector_definitions()
            bad_definitions["volumes"][0]["polygon"] = [[40.0, -3.8], [40.1, -3.7]]
            (bundle / "tma_definitions.json").write_text(json.dumps(valid_tma_definitions()), encoding="utf-8")
            (bundle / "tma_layout.json").write_text(json.dumps(valid_tma_layout()), encoding="utf-8")
            (bundle / "sector_definitions.json").write_text(json.dumps(bad_definitions), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least 3 points"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_rejects_legacy_sector_configs_and_influence_in_source(self) -> None:
        for fname in ("sector_configs.json", "sector_influence.json", "tma_structure.json"):
            with self.subTest(file=fname), tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
                bundle.mkdir(parents=True, exist_ok=True)
                (bundle / "tma_definitions.json").write_text(json.dumps(valid_tma_definitions()), encoding="utf-8")
                (bundle / "tma_layout.json").write_text(json.dumps(valid_tma_layout()), encoding="utf-8")
                (bundle / "sector_definitions.json").write_text(json.dumps(valid_sector_definitions()), encoding="utf-8")
                (bundle / fname).write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "generated at publish"):
                    MODULE.build_manifest(root, commit_sha="test-commit")

    def test_tma_coordination_alone_is_not_a_sector_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "tma_coordination.json").write_text(json.dumps(valid_tma_coordination()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing sector bundle files"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_valid_acc_bundle_records_airspace_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fir = root / "L" / "LE" / "LECM"
            fir.mkdir(parents=True, exist_ok=True)
            (fir / "acc_definitions.json").write_text(json.dumps(valid_acc_definitions()), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            files = manifest["bundles"]["L/LE/LECM"]["files"]
            self.assertEqual(["community.airspace_files"], files["acc_definitions"]["requires"])
            self.assertEqual("L/LE/LECM/acc_definitions.json", files["acc_definitions"]["repo_path"])

    def test_valid_tma_bundle_records_airspace_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "BARCELONA_TMA"
            shutil.copytree(REPO_ROOT / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA", bundle)
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            files = manifest["bundles"]["L/LE/BARCELONA_TMA"]["files"]
            self.assertEqual(["community.airspace_files"], files["tma_definitions"]["requires"])
            self.assertEqual(["community.airspace_files"], files["tma_layout"]["requires"])
            self.assertEqual(["community.airspace_files"], files["tma_coordination"]["requires"])
            self.assertEqual("L/LE/BARCELONA_TMA/tma_definitions.json", files["tma_definitions"]["repo_path"])

    def definitions_error(self, polygon: list[list[float]]) -> str | None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sector_definitions.json"
            definitions = valid_sector_definitions()
            definitions["volumes"][0]["polygon"] = polygon
            path.write_text(json.dumps(definitions), encoding="utf-8")
            try:
                MODULE.validate_sector_definitions_file(path, Path(tmp_dir))
            except ValueError as error:
                return str(error)
            return None

    def test_validate_sector_definitions_accepts_simple_rings(self) -> None:
        square = [[40.0, -4.0], [40.0, -3.0], [41.0, -3.0], [41.0, -4.0]]
        self.assertIsNone(self.definitions_error(square))
        self.assertIsNone(self.definitions_error(square + [square[0]]), "a closing point equal to the first is allowed")
        notch = [[0.0, 0.0], [0.0, 4.0], [4.0, 4.0], [4.0, 0.0], [2.0, 0.0], [2.0, 2.0], [1.0, 1.0]]
        self.assertIsNone(self.definitions_error(notch))

    def test_validate_sector_definitions_rejects_a_ring_that_crosses_itself(self) -> None:
        bow_tie = [[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]]
        self.assertRegex(self.definitions_error(bow_tie) or "", "crosses itself")

    def test_validate_sector_definitions_rejects_a_keyhole_that_revisits_a_point(self) -> None:
        keyhole = [
            [0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0],
            [4.0, 0.0], [4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0], [4.0, 0.0],
        ]
        self.assertRegex(self.definitions_error(keyhole) or "", "revisits a point")

    def test_validate_sector_definitions_rejects_a_repeated_neighbour_point(self) -> None:
        repeated = [[0.0, 0.0], [0.0, 4.0], [0.0, 4.0], [4.0, 4.0], [4.0, 0.0]]
        self.assertRegex(self.definitions_error(repeated) or "", "repeats the point of its neighbour")

    def test_validate_sector_definitions_rejects_edges_that_touch_or_fold_back(self) -> None:
        touching = [[0.0, 0.0], [0.0, 4.0], [4.0, 4.0], [4.0, 0.0], [2.0, 0.0], [2.0, 4.0]]
        self.assertRegex(self.definitions_error(touching) or "", "crosses itself")
        spike = [[0.0, 0.0], [0.0, 4.0], [4.0, 4.0], [4.0, 2.0], [6.0, 2.0], [5.0, 2.0], [4.0, 0.0]]
        self.assertRegex(self.definitions_error(spike) or "", "folds back|crosses itself")
        self.assertRegex(MODULE.polygon_ring_defect([[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]) or "", "folds back")

    def test_safe_repo_path_rejects_paths_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            root.mkdir(parents=True, exist_ok=True)
            outsider = Path(tmp_dir) / "outside" / "sector_configs.json"
            outsider.parent.mkdir(parents=True, exist_ok=True)
            outsider.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.safe_repo_path(outsider, root)


if __name__ == "__main__":
    unittest.main()
