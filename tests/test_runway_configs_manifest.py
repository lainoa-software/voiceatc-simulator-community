import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "runway_configs_manifest.py"
SPEC = importlib.util.spec_from_file_location("runway_configs_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RunwayConfigsManifestTests(unittest.TestCase):
    def test_repository_contains_only_plural_runway_config_filenames(self) -> None:
        legacy_files = MODULE.legacy_runway_files(REPO_ROOT)
        self.assertEqual([], legacy_files, f"Legacy runway config filenames found: {legacy_files}")

    def test_build_manifest_rejects_legacy_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            legacy_file = root / "E" / "ES" / "TEST" / "TEST_APP" / "ESSB" / "runway_config.json"
            legacy_file.parent.mkdir(parents=True, exist_ok=True)
            legacy_file.write_text(
                json.dumps(
                    {
                        "airport": "ESSB",
                        "runway_configurations": [{"id": "TEST", "arr": "12", "dep": "30"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "legacy runway filename"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_build_manifest_accepts_plural_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            valid_file = root / "E" / "ES" / "TEST" / "TEST_APP" / "ESSB" / "runway_configs.json"
            valid_file.parent.mkdir(parents=True, exist_ok=True)
            valid_file.write_text(
                json.dumps(
                    {
                        "airport": "ESSB",
                        "runway_configurations": [{"id": "TEST", "arr": "12", "dep": "30"}],
                    }
                ),
                encoding="utf-8",
            )

            manifest = MODULE.build_manifest(root, commit_sha="test-commit")

            self.assertIn("ESSB", manifest["airports"])
            self.assertEqual(
                "E/ES/TEST/TEST_APP/ESSB/runway_configs.json",
                manifest["airports"]["ESSB"]["repo_path"],
            )

    def test_build_manifest_rejects_unpadded_runway_ident(self) -> None:
        # PHNL shipped '8L 8R 4R'. The game compares against Navigraph's padded
        # identifiers without padding either side, so those rows resolved to no
        # runways at all and nothing reported it.
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_file = root / "P" / "PH" / "TEST" / "TEST_TMA" / "PHNL" / "runway_configs.json"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(
                json.dumps(
                    {
                        "airport": "PHNL",
                        "runway_configurations": [{"id": "EAST", "arr": "8L 8R", "dep": "8L"}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "zero-padded identifier"):
                MODULE.build_manifest(root, commit_sha="test-commit")

    def test_runway_idents_splits_every_separator_the_game_accepts(self) -> None:
        self.assertEqual(["08L", "08R", "04R"], MODULE.runway_idents("08L 08R 04R"))
        self.assertEqual(["08L", "26R"], MODULE.runway_idents("08L,26R"))
        self.assertEqual(["08L", "26R"], MODULE.runway_idents("08L|26R"))
        # '/' is what the game normalises the others to, and how charts write a
        # runway pair, so it must split rather than read as one identifier.
        self.assertEqual(["08L", "26R"], MODULE.runway_idents("08L/26R"))
        self.assertEqual(["31R", "22L"], MODULE.runway_idents("31R, 22L"))
        self.assertEqual(["08L", "26R"], MODULE.runway_idents(["08L", "26R"]))
        self.assertEqual([], MODULE.runway_idents("   "))

    def test_repository_runway_idents_are_zero_padded(self) -> None:
        offenders: list[str] = []
        for path in MODULE.runway_files(REPO_ROOT):
            payload = json.loads(path.read_text(encoding="utf-8"))
            configs = payload.get("runway_configurations", payload.get("runway_configs", []))
            for row in configs:
                for key in ("arr", "dep"):
                    for ident in MODULE.runway_idents(row.get(key, "")):
                        if not MODULE.RUNWAY_IDENT_RE.match(ident):
                            relative = path.relative_to(REPO_ROOT).as_posix()
                            offenders.append(f"{relative} {row.get('id')} {key}={ident}")
        self.assertEqual([], offenders, f"Unpadded runway identifiers: {offenders}")


if __name__ == "__main__":
    unittest.main()
