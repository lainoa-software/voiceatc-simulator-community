import importlib.util
import json
import math
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


def great_circle_distance_nm(latitude: float, longitude: float) -> float:
    latitude_1 = math.radians(KJFK_LATITUDE)
    longitude_1 = math.radians(KJFK_LONGITUDE)
    latitude_2 = math.radians(latitude)
    longitude_2 = math.radians(longitude)
    delta_latitude = latitude_2 - latitude_1
    delta_longitude = longitude_2 - longitude_1
    haversine = (
        math.sin(delta_latitude / 2.0) ** 2
        + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(delta_longitude / 2.0) ** 2
    )
    return EARTH_RADIUS_NM * 2.0 * math.asin(math.sqrt(haversine))


def valid_sector_configs() -> dict[str, object]:
    return {
        "sector_configs": [
            {
                "sector_config_id": "CFG_1",
                "runway_configs": ["NORTH"],
                "sectors": [{"sector_ids": "LEMDAAA", "frequency": "119.100"}],
            }
        ]
    }


def valid_sector_definitions() -> dict[str, object]:
    return {
        "sector_definitions": [
            {
                "sector_id": "LEMDAAA",
                "lower_limit": 0,
                "higher_limit": 24500,
                "polygon": [[40.0, -3.8], [40.1, -3.7], [40.2, -3.8]],
            }
        ]
    }


def valid_sector_influence() -> dict[str, object]:
    return {
        "sector_influences": [
            {
                "sector_id": "LEMDAAA",
                "airports": ["LEMD"],
            }
        ]
    }


class SectorDataManifestTests(unittest.TestCase):
    def test_repository_contains_expected_sector_bundle_paths(self) -> None:
        manifest = MODULE.build_manifest(REPO_ROOT, commit_sha="test-commit")
        core_bundles = {
            "G/GC/GCCC/GCCC_MAIN/CANARIAS_TMA",
            "K/KZNY/JFK_TMA",
            "L/LE/LECB/LECB_E/PALMA_TMA",
            "L/LE/LECB/LECB_W/BARCELONA_TMA",
            "L/LE/LECB/LECB_W/VALENCIA_TMA",
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

    def test_kjfk_bundle_uses_full_current_n90_envelope(self) -> None:
        bundle = REPO_ROOT / "K" / "KZNY" / "JFK_TMA"
        definitions = json.loads((bundle / "sector_definitions.json").read_text(encoding="utf-8"))
        influence = json.loads((bundle / "sector_influence.json").read_text(encoding="utf-8"))

        self.assertEqual("KJFK", definitions["airport"])
        self.assertNotIn("source", definitions)

        sector_definitions = definitions["sector_definitions"]
        self.assertEqual(1, len(sector_definitions))
        sector = sector_definitions[0]
        self.assertEqual("KJFKAPP", sector["sector_id"])
        self.assertEqual(0, sector["lower_limit"])
        self.assertEqual(19000, sector["higher_limit"])

        polygon = sector["polygon"]
        self.assertEqual(203, len(polygon))
        self.assertEqual(polygon[0], polygon[-1])
        latitudes = [point[0] for point in polygon]
        longitudes = [point[1] for point in polygon]
        self.assertAlmostEqual(39.63990, min(latitudes), places=5)
        self.assertAlmostEqual(42.48541, max(latitudes), places=5)
        self.assertAlmostEqual(-75.50005, min(longitudes), places=5)
        self.assertAlmostEqual(-71.77389, max(longitudes), places=5)

        maximum_distance_nm = max(
            great_circle_distance_nm(latitude, longitude) for latitude, longitude in polygon
        )
        self.assertGreaterEqual(maximum_distance_nm, 112.0)
        self.assertLessEqual(maximum_distance_nm, 114.0)

        terminal_owned_feeders = {
            "ATHOS": (42.24708, -73.81210),
            "DANZI": (42.17829, -74.95672),
            "PARCH": (41.09923, -72.12074),
            "PAWLN": (41.76986, -73.60073),
            "YODAA": (41.72255, -74.03132),
        }
        for fix_name, (latitude, longitude) in terminal_owned_feeders.items():
            self.assertTrue(
                polygon_contains(polygon, latitude, longitude),
                f"Expected {fix_name} to be inside the full N90 envelope",
            )

        center_owned_feeders = {
            "ALB": (42.74728, -73.80318),
            "ENE": (43.42567, -70.61352),
            "SIE": (39.09551, -74.80034),
        }
        for fix_name, (latitude, longitude) in center_owned_feeders.items():
            self.assertFalse(
                polygon_contains(polygon, latitude, longitude),
                f"Expected {fix_name} to remain outside the N90 envelope",
            )

        sector_influences = influence["sector_influences"]
        self.assertEqual(1, len(sector_influences))
        self.assertEqual("KJFKAPP", sector_influences[0]["sector_id"])
        self.assertEqual({"KJFK", "KFRG"}, set(sector_influences[0]["airports"]))

    def test_build_manifest_rejects_missing_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "sector_configs.json").write_text(json.dumps(valid_sector_configs()), encoding="utf-8")
            (bundle / "sector_definitions.json").write_text(json.dumps(valid_sector_definitions()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing sector bundle files"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_sector_bundle_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            (bundle / "sector_configs.json").write_text("{bad json", encoding="utf-8")
            (bundle / "sector_definitions.json").write_text(json.dumps(valid_sector_definitions()), encoding="utf-8")
            (bundle / "sector_influence.json").write_text(json.dumps(valid_sector_influence()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_sector_definitions_rejects_short_polygon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = root / "L" / "LE" / "TEST" / "TEST_TMA"
            bundle.mkdir(parents=True, exist_ok=True)
            bad_definitions = valid_sector_definitions()
            bad_definitions["sector_definitions"][0]["polygon"] = [[40.0, -3.8], [40.1, -3.7]]
            (bundle / "sector_configs.json").write_text(json.dumps(valid_sector_configs()), encoding="utf-8")
            (bundle / "sector_definitions.json").write_text(json.dumps(bad_definitions), encoding="utf-8")
            (bundle / "sector_influence.json").write_text(json.dumps(valid_sector_influence()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least 3 points"):
                MODULE.build_manifest(root, commit_sha="test-commit")

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
