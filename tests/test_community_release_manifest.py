import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "community_release_manifest.py"
SPEC = importlib.util.spec_from_file_location("community_release_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_fixture_repo(root: Path) -> None:
    write_json(
        root / "documentation" / "content_hierarchy.json",
        {
            "nationality_areas": {"E": ["EH"], "L": ["LE"]},
            "release_compatibility": {
                "color_profile_aliases": {},
                "retention": "until_explicit_deprecation",
            }
        },
    )
    routes_path = root / "ROUTES" / "routes.tsv"
    routes_path.parent.mkdir(parents=True, exist_ok=True)
    routes_path.write_text(
        "\n".join(
            [
                "airac 2602",
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR",
                "LEMD\tLEBL\tLEMD DCT TEST DCT LEBL\t2601\tLainoaSoftware",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "ROUTES" / "routes_legacy.tsv").write_bytes(routes_path.read_bytes())

    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "mva.json",
        {
            "airport": "LEMD",
            "mva_areas": [
                {
                    "area_id": "AREA_1",
                    "minimum_altitude_ft": 3000,
                    "polygon": [[40.0, -3.8], [40.1, -3.7], [40.2, -3.8]],
                    "labels": [{"text": "30", "position": [40.1, -3.75]}],
                }
            ],
        },
    )
    write_json(
        root / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA" / "mva.json",
        {
            "airport": "LEBL",
            "mva_areas": [
                {
                    "area_id": "AREA_1",
                    "minimum_altitude_ft": 4000,
                    "polygon": [[41.2, 2.0], [41.3, 2.1], [41.4, 2.0]],
                }
            ],
        },
    )

    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "LEMD" / "runway_configs.json",
        {
            "airport": "LEMD",
            "runway_configurations": [{"id": "NORTH", "arr": "32L", "dep": "36R"}],
        },
    )
    write_json(
        root / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA" / "LEBL" / "runway_configs.json",
        {
            "airport": "LEBL",
            "runway_configurations": [{"id": "WEST", "arr": "24R", "dep": "24L"}],
        },
    )

    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "sector_configs.json",
        {
            "sector_configs": [
                {
                    "sector_config_id": "MADRID_CORE",
                    "runway_configs": ["NORTH"],
                    "sectors": [{"sector_id": "LEMDAAA", "frequency": "119.100"}],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "sector_definitions.json",
        {
            "sector_definitions": [
                {
                    "sector_id": "LEMDAAA",
                    "lower_limit": 0,
                    "higher_limit": 24500,
                    "polygon": [[40.0, -3.8], [40.1, -3.7], [40.2, -3.8]],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "sector_influence.json",
        {
            "sector_influences": [
                {
                    "sector_id": "LEMDAAA",
                    "airports": ["LEMD"],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA" / "sector_configs.json",
        {
            "sector_configs": [
                {
                    "sector_config_id": "BARCELONA_CORE",
                    "runway_configs": ["WEST"],
                    "sectors": [{"sector_id": "LEBLAAA", "frequency": "131.125"}],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA" / "sector_definitions.json",
        {
            "sector_definitions": [
                {
                    "sector_id": "LEBLAAA",
                    "lower_limit": 0,
                    "higher_limit": 24500,
                    "polygon": [[41.2, 2.0], [41.3, 2.1], [41.4, 2.0]],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA" / "sector_influence.json",
        {
            "sector_influences": [
                {
                    "sector_id": "LEBLAAA",
                    "airports": ["LEBL"],
                }
            ]
        },
    )
    write_json(
        root / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "misc_drawings.json",
        {
            "airports": ["LEMD", "LETO"],
            "line_sections": [
                {
                    "color": "STAR",
                    "points": [[40.4, -3.7], [40.5, -3.6]],
                }
            ],
            "labels": [{"text": "TEST", "lat": 40.45, "lon": -3.65}],
        },
    )
    write_json(
        root / "L" / "LE" / "colors.json",
        {
            "assumed_tfc_color": "3bf451",
            "bg_color": "080808",
        },
    )
    write_json(
        root / "L" / "LE" / "style.json",
        {
            "defined_symbols": {"diamond": {"type": "wireframe", "draw": "M 0 -7 L 7 0 L 0 7 L -7 0 L 0 -7", "connection_points": [[0, -7], [7, 0], [0, 7], [-7, 0]]}},
            "assumed_symbol": "diamond",
        },
    )
    write_json(
        root / "E" / "EH" / "colors.json",
        {
            "assumed_tfc_color": "a5a5a7",
            "bg_color": "071010",
        },
    )
    write_json(
        root / "E" / "EH" / "style.json",
        {
            "defined_symbols": {"square": {"type": "wireframe", "draw": "M -7 -7 L 7 -7 L 7 7 L -7 7 L -7 -7", "connection_points": [[-7, -7], [7, -7], [7, 7], [-7, 7]]}},
            "assumed_symbol": "square",
        },
    )


def add_us_region_profile(root: Path) -> None:
    aliases = [f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)]
    write_json(
        root / "documentation" / "content_hierarchy.json",
        {
            "nationality_areas": {"E": ["EH"], "K": [], "L": ["LE"]},
            "release_compatibility": {
                "color_profile_aliases": {"K": aliases},
                "retention": "until_explicit_deprecation",
            }
        },
    )
    write_json(
        root / "K" / "colors.json",
        {
            "assumed_tfc_color": "3bf451",
            "bg_color": "080808",
        },
    )
    write_json(
        root / "K" / "style.json",
        {
            "defined_symbols": {
                "diamond": {
                    "type": "wireframe",
                    "draw": "M 0 -7 L 7 0 L 0 7 L -7 0 L 0 -7",
                    "connection_points": [[0, -7], [7, 0], [0, 7], [-7, 0]],
                }
            },
            "assumed_symbol": "diamond",
        },
    )


class CommunityReleaseManifestTests(unittest.TestCase):
    def test_mapped_zip_rejects_normalized_archive_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "K" / "colors.json"
            write_json(source, {"bg_color": "080808"})
            with self.assertRaisesRegex(ValueError, "duplicate archive path"):
                MODULE.build_deterministic_zip_from_sources(
                    root,
                    {
                        "K/KA/colors.json": "K/colors.json",
                        "K\\KA\\colors.json": "K/colors.json",
                    },
                    root / "color-profiles.zip",
                )

    def test_build_release_bundle_creates_expected_assets_and_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            build_fixture_repo(root)
            output_dir = root / "build" / "release"

            bundle = MODULE.build_release_bundle(
                output_dir=output_dir,
                release_tag="daily-2026-03-18",
                published_at="2026-03-18T01:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )

            self.assertEqual("2602", bundle["airac"])
            self.assertEqual("routes-2602.tsv", bundle["assets"]["routes_tsv"]["asset_name"])
            self.assertEqual(
                "routes-rich-2602.tsv",
                bundle["assets"]["routes_rich_tsv"]["asset_name"],
            )
            self.assertEqual("mva-2602.zip", bundle["assets"]["mva_zip"]["asset_name"])
            self.assertEqual("runway-configs-2602.zip", bundle["assets"]["runway_configs_zip"]["asset_name"])
            self.assertEqual("sector-data-2602.zip", bundle["assets"]["sector_data_zip"]["asset_name"])
            self.assertEqual("misc-drawings-2602.zip", bundle["assets"]["misc_drawings_zip"]["asset_name"])
            self.assertEqual("color-profiles-2602.zip", bundle["assets"]["color_profiles_zip"]["asset_name"])
            self.assertEqual("release-manifest.json", bundle["assets"]["release_manifest"]["asset_name"])

            release_manifest = bundle["manifests"]["release"]
            self.assertEqual(4, release_manifest["schema_version"])
            self.assertEqual("daily-2026-03-18", release_manifest["release_tag"])
            self.assertEqual("Daily Community Release - Wednesday 2026-03-18", release_manifest["release_title"])
            self.assertIn("mva_zip", release_manifest["assets"])
            self.assertIn("runway_configs_zip", release_manifest["assets"])
            self.assertIn("sector_data_zip", release_manifest["assets"])
            self.assertIn("misc_drawings_zip", release_manifest["assets"])
            self.assertIn("color_profiles_zip", release_manifest["assets"])
            self.assertIn("routes_rich_tsv", release_manifest["assets"])
            self.assertEqual("2601", release_manifest["assets"]["routes_tsv"]["source_airac"])
            self.assertTrue(release_manifest["assets"]["routes_tsv"]["compatibility_fallback"])

            mva_manifest = bundle["manifests"]["mva"]
            self.assertEqual(2, mva_manifest["schema_version"])
            self.assertEqual("mva-2602.zip", mva_manifest["asset_name"])
            self.assertEqual(2, mva_manifest["airport_count"])

            runway_manifest = bundle["manifests"]["runway_configs"]
            self.assertEqual(2, runway_manifest["schema_version"])
            self.assertEqual("runway-configs-2602.zip", runway_manifest["asset_name"])
            self.assertEqual(2, runway_manifest["airport_count"])

            sector_manifest = bundle["manifests"]["sector_data"]
            self.assertEqual(2, sector_manifest["schema_version"])
            self.assertEqual("sector-data-2602.zip", sector_manifest["asset_name"])
            self.assertEqual(2, sector_manifest["bundle_count"])

            misc_drawings_manifest = bundle["manifests"]["misc_drawings"]
            self.assertEqual(2, misc_drawings_manifest["schema_version"])
            self.assertEqual("misc-drawings-2602.zip", misc_drawings_manifest["asset_name"])
            self.assertEqual(2, misc_drawings_manifest["airport_count"])

            color_profiles_manifest = bundle["manifests"]["color_profiles"]
            self.assertEqual(2, color_profiles_manifest["schema_version"])
            self.assertEqual("color-profiles-2602.zip", color_profiles_manifest["asset_name"])
            self.assertEqual(2, color_profiles_manifest["profile_count"])

    def test_zip_assets_are_deterministic_and_preserve_repo_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            build_fixture_repo(root)

            first = MODULE.build_release_bundle(
                output_dir=root / "build" / "one",
                release_tag="daily-2026-03-18",
                published_at="2026-03-18T01:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )
            second = MODULE.build_release_bundle(
                output_dir=root / "build" / "two",
                release_tag="daily-2026-03-18",
                published_at="2026-03-18T01:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )

            self.assertEqual(first["assets"]["mva_zip"]["sha256"], second["assets"]["mva_zip"]["sha256"])
            self.assertEqual(
                first["assets"]["runway_configs_zip"]["sha256"],
                second["assets"]["runway_configs_zip"]["sha256"],
            )
            self.assertEqual(
                first["assets"]["sector_data_zip"]["sha256"],
                second["assets"]["sector_data_zip"]["sha256"],
            )
            self.assertEqual(
                first["assets"]["misc_drawings_zip"]["sha256"],
                second["assets"]["misc_drawings_zip"]["sha256"],
            )
            self.assertEqual(
                first["assets"]["color_profiles_zip"]["sha256"],
                second["assets"]["color_profiles_zip"]["sha256"],
            )

            with zipfile.ZipFile(first["assets"]["mva_zip"]["path"], "r") as archive:
                self.assertEqual(
                    [
                        "L/LE/LECB/LECB_W/BARCELONA_TMA/mva.json",
                        "L/LE/LECM/LECM_R2/MADRID_TMA/mva.json",
                    ],
                    archive.namelist(),
                )

            with zipfile.ZipFile(first["assets"]["runway_configs_zip"]["path"], "r") as archive:
                self.assertEqual(
                    [
                        "L/LE/LECB/LECB_W/BARCELONA_TMA/LEBL/runway_configs.json",
                        "L/LE/LECM/LECM_R2/MADRID_TMA/LEMD/runway_configs.json",
                    ],
                    archive.namelist(),
                )

            with zipfile.ZipFile(first["assets"]["sector_data_zip"]["path"], "r") as archive:
                self.assertEqual(
                    [
                        "L/LE/LECB/LECB_W/BARCELONA_TMA/sector_configs.json",
                        "L/LE/LECB/LECB_W/BARCELONA_TMA/sector_definitions.json",
                        "L/LE/LECB/LECB_W/BARCELONA_TMA/sector_influence.json",
                        "L/LE/LECM/LECM_R2/MADRID_TMA/sector_configs.json",
                        "L/LE/LECM/LECM_R2/MADRID_TMA/sector_definitions.json",
                        "L/LE/LECM/LECM_R2/MADRID_TMA/sector_influence.json",
                    ],
                    archive.namelist(),
                )

            with zipfile.ZipFile(first["assets"]["misc_drawings_zip"]["path"], "r") as archive:
                self.assertEqual(
                    [
                        "L/LE/LECM/LECM_R2/MADRID_TMA/misc_drawings.json",
                    ],
                    archive.namelist(),
                )

            with zipfile.ZipFile(first["assets"]["color_profiles_zip"]["path"], "r") as archive:
                self.assertEqual(
                    [
                        "E/EH/colors.json",
                        "E/EH/style.json",
                        "L/LE/colors.json",
                        "L/LE/style.json",
                    ],
                    archive.namelist(),
                )

    def test_build_release_bundle_accepts_suffixed_manual_release_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            build_fixture_repo(root)

            bundle = MODULE.build_release_bundle(
                output_dir=root / "build" / "manual",
                release_tag="daily-2026-03-18-b",
                release_title="Daily Community Release - Wednesday 2026-03-18 b",
                published_at="2026-03-18T12:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )

            release_manifest = bundle["manifests"]["release"]
            self.assertEqual("daily-2026-03-18-b", release_manifest["release_tag"])
            self.assertEqual("Daily Community Release - Wednesday 2026-03-18 b", release_manifest["release_title"])

    def test_us_region_profile_is_projected_to_deterministic_legacy_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            build_fixture_repo(root)
            add_us_region_profile(root)

            first = MODULE.build_release_bundle(
                output_dir=root / "build" / "one",
                release_tag="daily-2026-03-18",
                published_at="2026-03-18T01:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )
            second = MODULE.build_release_bundle(
                output_dir=root / "build" / "two",
                release_tag="daily-2026-03-18",
                published_at="2026-03-18T01:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )

            color_manifest = first["manifests"]["color_profiles"]
            aliases = {f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)}
            self.assertEqual(2, color_manifest["schema_version"])
            self.assertEqual(28, color_manifest["profile_count"])
            self.assertNotIn("K", color_manifest["profiles"])
            self.assertEqual(aliases, {scope for scope in color_manifest["profiles"] if scope.startswith("K/")})
            self.assertEqual(
                first["assets"]["color_profiles_zip"]["sha256"],
                second["assets"]["color_profiles_zip"]["sha256"],
            )

            with zipfile.ZipFile(first["assets"]["color_profiles_zip"]["path"], "r") as archive:
                names = archive.namelist()
                self.assertEqual(sorted(names), names)
                self.assertEqual(56, len(names))
                self.assertNotIn("K/colors.json", names)
                self.assertNotIn("K/style.json", names)
                canonical_colors = (root / "K" / "colors.json").read_bytes()
                canonical_style = (root / "K" / "style.json").read_bytes()
                for alias in aliases:
                    self.assertEqual(canonical_colors, archive.read(f"{alias}/colors.json"))
                    self.assertEqual(canonical_style, archive.read(f"{alias}/style.json"))


if __name__ == "__main__":
    unittest.main()
