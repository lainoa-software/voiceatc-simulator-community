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
        self.write_registry(fixture_registry())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_json(self, relative: str, payload: dict[str, object]) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def errors(self) -> list[str]:
        return MODULE.validate_repository(self.root)

    def report(self) -> str:
        return MODULE.format_report(MODULE.collect_findings(self.root))

    def write_registry(self, registry: dict[str, object]) -> None:
        # Indented like the real registry: --register edits it as text, so the
        # layout is part of the contract under test.
        path = self.root / "documentation" / "content_hierarchy.json"
        path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8", newline="\n")

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

    def test_reports_one_unregistered_scope_block_for_many_files(self) -> None:
        self.write_json("K/KZHU/MKE_TMA/KMKE/runway_configs.json", {"airport": "KMKE"})
        self.write_json("K/KZHU/MKE_TMA/KMKE/procedure_options.json", {"airport": "KMKE"})
        self.write_json("K/KZHU/MKE_TMA/sector_influence.json", {"sector_id": "X", "airports": ["KMKE"]})
        report = self.report()
        self.assertIn("K/KZHU/MKE_TMA is not a registered terminal scope (3 files affected).", report)
        self.assertIn('"K/KZHU/MKE_TMA": ["KMKE"],', report)
        self.assertIn("--register K/KZHU/MKE_TMA", report)
        # The whole family collapses: no per-file repetition of the same cause.
        self.assertNotIn("outside a registered terminal scope", report)
        self.assertNotIn("referenced airport 'KMKE' is not registered", report)

    def test_wrong_scope_for_registered_airport_is_not_grouped(self) -> None:
        # The airport is registered elsewhere, so the remedy is to move it, not
        # to register a new scope. That message must survive ungrouped.
        self.write_json("K/KZFW/AUSTIN_TMA/KAUS/runway_configs.json", {"airport": "KAUS"})
        report = self.report()
        self.assertIn("belongs in terminal scope 'K/KZHU/AUSTIN_TMA'", report)
        self.assertNotIn("--register", report)

    def test_register_adds_scope_and_clears_validation(self) -> None:
        self.write_json("K/KZHU/MKE_TMA/KMKE/runway_configs.json", {"airport": "KMKE"})
        self.assertNotEqual([], self.errors())
        MODULE.register_scope("K/KZHU/MKE_TMA", self.root)
        self.assertEqual([], self.errors())
        registry = json.loads((self.root / "documentation" / "content_hierarchy.json").read_text(encoding="utf-8"))
        self.assertEqual(["KMKE"], registry["terminal_scopes"]["K/KZHU/MKE_TMA"])

    def test_register_preserves_existing_entry_order(self) -> None:
        self.write_json("K/KZHU/MKE_TMA/KMKE/runway_configs.json", {"airport": "KMKE"})
        before = list(fixture_registry()["terminal_scopes"])
        MODULE.register_scope("K/KZHU/MKE_TMA", self.root)
        after = list(
            json.loads((self.root / "documentation" / "content_hierarchy.json").read_text(encoding="utf-8"))[
                "terminal_scopes"
            ]
        )
        self.assertEqual(before, [key for key in after if key != "K/KZHU/MKE_TMA"])
        # Slotted beside its closest relative rather than appended at the end.
        self.assertEqual(after.index("K/KZHU/AUSTIN_TMA") + 1, after.index("K/KZHU/MKE_TMA"))

    def test_register_adds_a_new_airport_to_an_already_registered_scope(self) -> None:
        # The common case: a second airport joins a terminal area that already exists.
        self.write_json("K/KZHU/AUSTIN_TMA/KSAT/runway_configs.json", {"airport": "KSAT"})
        self.assertNotEqual([], self.errors())
        message = MODULE.register_scope("K/KZHU/AUSTIN_TMA", self.root)
        self.assertIn("KSAT", message)
        self.assertEqual([], self.errors())
        registry = json.loads((self.root / "documentation" / "content_hierarchy.json").read_text(encoding="utf-8"))
        self.assertEqual(["KAUS", "KSAT"], registry["terminal_scopes"]["K/KZHU/AUSTIN_TMA"])

    def test_register_keeps_airports_that_have_no_folder(self) -> None:
        # Terminal-level data may name an airport that owns no folder; it must survive.
        self.write_json("K/KZHU/AUSTIN_TMA/KSAT/runway_configs.json", {"airport": "KSAT"})
        MODULE.register_scope("K/KZHU/AUSTIN_TMA", self.root)
        registry = json.loads((self.root / "documentation" / "content_hierarchy.json").read_text(encoding="utf-8"))
        self.assertIn("KAUS", registry["terminal_scopes"]["K/KZHU/AUSTIN_TMA"])

    def test_register_is_idempotent(self) -> None:
        self.write_json("K/KZHU/MKE_TMA/KMKE/runway_configs.json", {"airport": "KMKE"})
        MODULE.register_scope("K/KZHU/MKE_TMA", self.root)
        first = (self.root / "documentation" / "content_hierarchy.json").read_bytes()
        self.assertIn("already registered", MODULE.register_scope("K/KZHU/MKE_TMA", self.root))
        self.assertEqual(first, (self.root / "documentation" / "content_hierarchy.json").read_bytes())

    def test_register_rejects_scope_with_no_airport_folders(self) -> None:
        (self.root / "K" / "KZHU" / "EMPTY_TMA").mkdir(parents=True)
        with self.assertRaises(SystemExit):
            MODULE.register_scope("K/KZHU/EMPTY_TMA", self.root)

    def test_register_rejects_unknown_operational_area(self) -> None:
        self.write_json("K/KZZZ/NOWHERE_TMA/KNOW/runway_configs.json", {"airport": "KNOW"})
        with self.assertRaises(SystemExit):
            MODULE.register_scope("K/KZZZ/NOWHERE_TMA", self.root)

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
