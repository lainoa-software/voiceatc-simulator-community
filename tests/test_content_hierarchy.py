import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "content_hierarchy.py"
SPEC = importlib.util.spec_from_file_location("content_hierarchy", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def fixture_registry() -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorities": {"nav": {}, "faa": {}},
        "nationality_areas": {"E": ["ED", "ES"], "K": []},
        "release_compatibility": {
            "color_profile_aliases": {},
            "retention": "until_explicit_deprecation",
        },
        "operational_areas": {
            "EDGG": {"authority": "nav", "kind": "fir"},
            "ESAA": {"authority": "nav", "kind": "fir"},
            "KZFW": {"authority": "faa", "kind": "artcc"},
            "KZHU": {"authority": "faa", "kind": "artcc"},
        },
        "terminal_scopes": {
            "E/ED/EDGG/FRANKFURT_TMA": ["EDDF"],
            "E/ES/ESAA/ESOS_Y/STOCKHOLM_TMA": ["ESSA"],
            "K/KZFW/DFW_TMA": ["KDFW"],
            "K/KZHU/AUSTIN_TMA": ["KAUS"],
        },
    }


class ContentHierarchyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        registry_path = self.root / "documentation" / "content_hierarchy.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(json.dumps(fixture_registry()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: dict[str, object]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def errors(self) -> list[str]:
        return MODULE.validate_repository(self.root)

    def write_registry(self, registry: dict[str, object]) -> None:
        path = self.root / "documentation" / "content_hierarchy.json"
        path.write_text(json.dumps(registry), encoding="utf-8")

    def test_accepts_paths_with_and_without_nationality_layer(self) -> None:
        self.write_json("E/ED/EDGG/FRANKFURT_TMA/EDDF/runway_configs.json", {"airport": "EDDF"})
        self.write_json("K/KZHU/AUSTIN_TMA/KAUS/runway_configs.json", {"airport": "KAUS"})
        self.write_json("K/colors.json", {"bg_color": "000000"})
        self.assertEqual([], self.errors())

    def test_rejects_kxxx_placeholder(self) -> None:
        self.write_json("K/KX/KXXX/KZHU/AUSTIN_TMA/KAUS/runway_configs.json", {"airport": "KAUS"})
        self.assertTrue(any("KXXX" in error and "placeholder" in error for error in self.errors()))

    def test_rejects_edxx_placeholder(self) -> None:
        self.write_json("E/ED/EDXX/EDGG/FRANKFURT_TMA/EDDF/runway_configs.json", {"airport": "EDDF"})
        self.assertTrue(any("EDXX" in error and "placeholder" in error for error in self.errors()))

    def test_rejects_esmm_as_fir(self) -> None:
        self.write_json("E/ES/ESMM/ESOS_Y/STOCKHOLM_TMA/ESSA/runway_configs.json", {"airport": "ESSA"})
        self.assertTrue(any("unknown operational identifier 'ESMM'" in error for error in self.errors()))

    def test_rejects_wrong_artcc(self) -> None:
        self.write_json("K/KZFW/AUSTIN_TMA/KAUS/runway_configs.json", {"airport": "KAUS"})
        self.assertTrue(any("KAUS" in error and "K/KZHU/AUSTIN_TMA" in error for error in self.errors()))

    def test_rejects_more_than_one_acc_group(self) -> None:
        self.write_json("K/KZHU/GROUP_A/GROUP_B/AUSTIN_TMA/KAUS/runway_configs.json", {"airport": "KAUS"})
        self.assertTrue(any("more than one ACC grouping" in error for error in self.errors()))

    def test_rejects_terminal_data_inside_airport_folder(self) -> None:
        self.write_json("K/KZHU/AUSTIN_TMA/KAUS/mva.json", {"airport": "KAUS"})
        self.assertTrue(any("must not be inside an airport folder" in error for error in self.errors()))

    def test_accepts_exact_release_alias_declaration_without_source_aliases(self) -> None:
        registry = fixture_registry()
        registry["release_compatibility"]["color_profile_aliases"] = {
            "K": sorted(MODULE.EXPECTED_US_COLOR_ALIASES)
        }
        self.write_registry(registry)
        self.write_json("K/colors.json", {"bg_color": "000000"})
        self.assertEqual([], self.errors())

    def test_rejects_incomplete_us_release_alias_declaration(self) -> None:
        registry = fixture_registry()
        registry["release_compatibility"]["color_profile_aliases"] = {"K": ["K/KA"]}
        self.write_registry(registry)
        self.write_json("K/colors.json", {"bg_color": "000000"})
        self.assertTrue(any("exactly K/KA through K/KZ" in error for error in self.errors()))

    def test_rejects_missing_release_compatibility_source(self) -> None:
        registry = fixture_registry()
        registry["release_compatibility"]["color_profile_aliases"] = {
            "K": sorted(MODULE.EXPECTED_US_COLOR_ALIASES)
        }
        self.write_registry(registry)
        self.assertTrue(any("source 'K' is missing colors.json" in error for error in self.errors()))

    def test_rejects_release_alias_directory_in_source(self) -> None:
        registry = fixture_registry()
        registry["release_compatibility"]["color_profile_aliases"] = {
            "K": sorted(MODULE.EXPECTED_US_COLOR_ALIASES)
        }
        self.write_registry(registry)
        self.write_json("K/colors.json", {"bg_color": "000000"})
        self.write_json("K/KA/colors.json", {"bg_color": "000000"})
        self.assertTrue(any("release-only compatibility alias must not exist" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
