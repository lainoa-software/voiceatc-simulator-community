import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "sector_data_manifest.py"
SPEC = importlib.util.spec_from_file_location("sector_data_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def valid_sector_configs() -> dict[str, object]:
    return {
        "sector_configs": [
            {
                "sector_config_id": "CFG_1",
                "runway_configs": ["NORTH"],
                "sectors": [{"sector_id": "LEMDAAA", "frequency": "119.100"}],
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
        self.assertEqual(
            {
                "G/GC/GCCC/GCCC_MAIN/CANARIAS_TMA",
                "L/LE/LECB/LECB_E/PALMA_TMA",
                "L/LE/LECB/LECB_W/BARCELONA_TMA",
                "L/LE/LECB/LECB_W/VALENCIA_TMA",
                "L/LE/LECM/LECM_R1/BILBAO_TMA",
                "L/LE/LECM/LECM_R1/GALICIA_TMA",
                "L/LE/LECM/LECM_R2/MADRID_TMA",
                "L/LE/LECM/LECS/MALAGA_TMA",
                "L/LE/LECM/LECS/SEVILLA_TMA",
            },
            set(manifest["bundles"].keys()),
        )

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
