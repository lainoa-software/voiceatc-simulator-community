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
        "defined_symbols": {
            "diamond": "101;010;101",
        },
        "assumed_symbol": "diamond",
    }


class ColorProfilesManifestTests(unittest.TestCase):
    def test_repository_contains_expected_scope_paths(self) -> None:
        manifest = MODULE.build_manifest(REPO_ROOT, commit_sha="test-commit")
        core_scopes = {"E/EH", "G/GC", "L/LE"}
        found_scopes = set(manifest["profiles"].keys())
        self.assertTrue(core_scopes.issubset(found_scopes), f"Missing core scopes: {core_scopes - found_scopes}")

    def test_build_manifest_accepts_country_fir_acc_tma_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for parts in [
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
                    "L/LE",
                    "L/LE/LECM",
                    "L/LE/LECM/LECM_R2",
                    "L/LE/LECM/LECM_R2/MADRID_TMA",
                },
                set(manifest["profiles"].keys()),
            )

    def test_build_manifest_rejects_missing_required_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            scope_dir = root / "L" / "LE"
            scope_dir.mkdir(parents=True, exist_ok=True)
            (scope_dir / "colors.json").write_text(json.dumps(valid_colors()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing color profile files"):
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


if __name__ == "__main__":
    unittest.main()
