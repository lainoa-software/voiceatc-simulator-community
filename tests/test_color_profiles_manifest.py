import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "color_profiles_manifest.py"
SPEC = importlib.util.spec_from_file_location("color_profiles_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def valid_colors() -> dict[str, object]:
    return {
        "assumed_tfc_color": "3bf451",
        "bg_color": "080808",
    }


def valid_style() -> dict[str, object]:
    return {
        "symbol_size": 0.6,
        "traildot_size": 0.15,
        "symbol_line_width": 2.0,
        "defined_symbols": {
            "diamond": {
                "type": "wireframe",
                "draw": "M 0 -7 L 7 0 L 0 7 L -7 0 L 0 -7",
                "connection_points": [[0, -7], [7, 0], [0, 7], [-7, 0]],
            },
        },
        "assumed_symbol": "diamond",
    }


def legacy_us_aliases() -> list[str]:
    return [f"K/K{chr(letter)}" for letter in range(ord("A"), ord("Z") + 1)]


def write_compatibility_registry(root: Path, aliases: dict[str, list[str]] | None = None) -> None:
    path = root / "documentation" / "content_hierarchy.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "nationality_areas": {"K": []},
                "release_compatibility": {
                    "color_profile_aliases": aliases or {},
                    "retention": "until_explicit_deprecation",
                }
            }
        ),
        encoding="utf-8",
    )


class ColorProfilesManifestTests(unittest.TestCase):
    def test_repository_contains_expected_scope_paths(self) -> None:
        manifest = MODULE.build_manifest(REPO_ROOT, commit_sha="test-commit")
        core_scopes = {"E/EH", "G/GC", "L/LE"}
        found_scopes = set(manifest["profiles"].keys())
        self.assertTrue(core_scopes.issubset(found_scopes), f"Missing core scopes: {core_scopes - found_scopes}")

    def test_repository_release_projection_matches_legacy_contract(self) -> None:
        canonical = MODULE.build_manifest(REPO_ROOT, commit_sha="test-commit")
        projection = MODULE.build_release_projection(REPO_ROOT, commit_sha="test-commit")
        aliases = set(legacy_us_aliases())

        canonical_scopes = set(canonical["profiles"])
        projection_scopes = set(projection["profiles"])

        # The single-segment K region scope is replaced by its 26 US aliases;
        # every multi-segment canonical scope passes through unchanged.
        self.assertNotIn("K", projection_scopes)
        self.assertEqual(canonical_scopes - {"K"}, projection_scopes - aliases)
        self.assertEqual(aliases, {scope for scope in projection_scopes if scope.startswith("K/")})

        # Archive sources cover every released file exactly once, mapping each alias
        # back to the canonical K source and leaving pass-through paths untouched.
        expected_archive_paths = {
            entry["repo_path"]
            for profile in projection["profiles"].values()
            for entry in profile["files"].values()
        }
        self.assertEqual(expected_archive_paths, set(projection["archive_sources"]))
        for scope, profile in projection["profiles"].items():
            for kind, entry in profile["files"].items():
                file_name = MODULE.PROFILE_FILE_NAMES[kind]
                self.assertEqual(f"{scope}/{file_name}", entry["repo_path"])
                if scope in aliases:
                    self.assertEqual(f"K/{file_name}", projection["archive_sources"][entry["repo_path"]])
                else:
                    self.assertEqual(entry["repo_path"], projection["archive_sources"][entry["repo_path"]])

    def test_build_manifest_accepts_region_country_fir_acc_tma_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for parts in [
                ("K",),
                ("L", "LE"),
                ("L", "LE", "LECM"),
                ("L", "LE", "LECM", "LECM_R2"),
                ("L", "LE", "LECM", "LECM_R2", "MADRID_TMA"),
            ]:
                scope_dir = root.joinpath(*parts)
                scope_dir.mkdir(parents=True, exist_ok=True)
                (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
                (scope_dir / "style.json").write_text(json.dumps(valid_style()), encoding="utf-8")

            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertEqual(
                {
                    "K",
                    "L/LE",
                    "L/LE/LECM",
                    "L/LE/LECM/LECM_R2",
                    "L/LE/LECM/LECM_R2/MADRID_TMA",
                },
                set(manifest["profiles"].keys()),
            )

    def test_build_manifest_accepts_colors_only_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertIn("L/LE", manifest["profiles"])
            self.assertNotIn("style", manifest["profiles"]["L/LE"]["files"])

    def test_release_projection_replaces_region_scope_with_exact_legacy_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "K"
            scope_dir.mkdir(parents=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(valid_style()), encoding="utf-8")
            aliases = legacy_us_aliases()
            write_compatibility_registry(root, {"K": aliases})

            canonical = MODULE.build_manifest(root, commit_sha="test-commit")
            projection = MODULE.build_release_projection(root, commit_sha="test-commit")

            self.assertEqual({"K"}, set(canonical["profiles"]))
            self.assertNotIn("K", projection["profiles"])
            self.assertEqual(set(aliases), set(projection["profiles"]))
            for alias in aliases:
                for kind in canonical["profiles"]["K"]["files"]:
                    file_name = MODULE.PROFILE_FILE_NAMES[kind]
                    public_entry = projection["profiles"][alias]["files"][kind]
                    source_entry = canonical["profiles"]["K"]["files"][kind]
                    self.assertEqual(source_entry["sha256"], public_entry["sha256"])
                    self.assertEqual(source_entry["size_bytes"], public_entry["size_bytes"])
                    archive_path = f"{alias}/{file_name}"
                    self.assertEqual(archive_path, public_entry["repo_path"])
                    self.assertEqual(f"K/{file_name}", projection["archive_sources"][archive_path])

    def test_release_projection_preserves_optional_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "K"
            scope_dir.mkdir(parents=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            write_compatibility_registry(root, {"K": legacy_us_aliases()})

            projection = MODULE.build_release_projection(root, commit_sha="test-commit")

            self.assertTrue(all(set(profile["files"]) == {"colors"} for profile in projection["profiles"].values()))
            self.assertEqual(26, len(projection["archive_sources"]))

    def test_release_projection_rejects_undeclared_region_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "K"
            scope_dir.mkdir(parents=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            write_compatibility_registry(root)

            with self.assertRaisesRegex(ValueError, "requires declared legacy release aliases"):
                MODULE.build_release_projection(root, commit_sha="test-commit")

    def test_release_projection_rejects_alias_source_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "K").mkdir(parents=True)
            (root / "K" / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            alias_dir = root / "K" / "KA"
            alias_dir.mkdir(parents=True)
            (alias_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            write_compatibility_registry(root, {"K": legacy_us_aliases()})

            with self.assertRaisesRegex(ValueError, "collides with source scope"):
                MODULE.build_release_projection(root, commit_sha="test-commit")

    def test_release_projection_rejects_missing_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            write_compatibility_registry(root, {"K": legacy_us_aliases()})

            with self.assertRaisesRegex(ValueError, "missing source scopes"):
                MODULE.build_release_projection(root, commit_sha="test-commit")

    def test_release_projection_rejects_aliases_for_unregistered_region(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "X"
            scope_dir.mkdir(parents=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            write_compatibility_registry(root, {"X": ["X/XA"]})

            with self.assertRaisesRegex(ValueError, "registered region scope"):
                MODULE.build_release_projection(root, commit_sha="test-commit")

    def test_build_manifest_rejects_missing_colors_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            (scope_dir / "style.json").write_text(json.dumps(valid_style()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing color profile files: colors"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_colors_rejects_invalid_hex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            bad_colors = valid_colors()
            bad_colors["assumed_tfc_color"] = "not-a-color"
            (scope_dir / "colors.json").write_text(json.dumps(bad_colors), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(valid_style()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hex color"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_rejects_invalid_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            bad_style = valid_style()
            bad_style["bg_color"] = "080808"
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(bad_style), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "style.json only accepts"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_accepts_numeric_config_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            style = valid_style()
            style["symbol_size"] = 0.8
            style["traildot_size"] = 0.2
            style["symbol_line_width"] = 3.0
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(style), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertIn("L/LE", manifest["profiles"])

    def test_validate_style_accepts_objective_symbol_height(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            style = valid_style()
            style["defined_symbols"]["diamond"]["height"] = 0.78
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(style), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertIn("L/LE", manifest["profiles"])

    def test_validate_style_rejects_invalid_objective_symbol_height(self) -> None:
        invalid_heights = [0, -0.1, True, "0.78", float("nan"), float("inf")]
        for invalid_height in invalid_heights:
            with self.subTest(height=invalid_height), tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                scope_dir = root / "L" / "LE"
                scope_dir.mkdir(parents=True, exist_ok=True)
                style = valid_style()
                style["defined_symbols"]["diamond"]["height"] = invalid_height
                (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
                (scope_dir / "style.json").write_text(json.dumps(style), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "height.*finite positive number"):
                    MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_accepts_label_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            style = valid_style()
            style["label"] = {
                "row_count": 2,
                "col_count": 1,
                "fields": [{"id": "CS", "row": 0, "col": 0, "content_source": "flight.cs"}],
            }
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(style), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertIn("L/LE", manifest["profiles"])

    def test_validate_style_rejects_non_object_label_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            bad_style = valid_style()
            bad_style["label"] = "full"
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(bad_style), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "'label' must be a non-empty object"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_rejects_invalid_symbol_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            bad_style = valid_style()
            bad_style["defined_symbols"]["diamond"] = 12345
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(bad_style), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be an object"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_rejects_symbol_missing_required_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            bad_style = valid_style()
            bad_style["defined_symbols"]["diamond"] = {"type": "wireframe", "draw": "M 0 0"}
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(bad_style), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required key"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_validate_style_rejects_legacy_bitmap_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            legacy_style = {
                "defined_symbols": {"diamond": "101;010;101"},
                "assumed_symbol": "diamond",
            }
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            (scope_dir / "style.json").write_text(json.dumps(legacy_style), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "legacy bitmap format"):
                MODULE.build_manifest(root, commit_sha="test-commit")


class ProfileFileKindTests(unittest.TestCase):
    def test_a_colour_profile_is_colors_plus_optional_style(self) -> None:
        self.assertEqual({"colors": "colors.json", "style": "style.json"}, MODULE.PROFILE_FILE_NAMES)
        self.assertEqual(("colors", "style"), MODULE.FILE_KIND_ORDER)

    def test_style_is_optional_beside_colors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "L" / "LE").mkdir(parents=True)
            (root / "L" / "LE" / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            manifest = MODULE.build_manifest(root, commit_sha="test-commit")
            self.assertEqual({"colors"}, set(manifest["profiles"]["L/LE"]["files"]))


if __name__ == "__main__":
    unittest.main()
