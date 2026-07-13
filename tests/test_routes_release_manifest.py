import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "routes_release_manifest.py"
SPEC = importlib.util.spec_from_file_location("routes_release_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RoutesReleaseManifestTests(unittest.TestCase):
    def test_build_routes_manifest_accepts_valid_routes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\t2602\tLainoaSoftware\n"
                "EGLL\tLEMD\tEGLL SAM UL9 NANDO LEMD\t2602\tLainoaSoftware\n",
                encoding="utf-8",
            )

            manifest = MODULE.build_routes_manifest(
                release_tag="daily-2026-03-15",
                asset_name="routes-2602.tsv",
                download_url="https://github.com/example/releases/download/daily-2026-03-15/routes-2602.tsv",
                published_at="2026-03-15T01:15:00Z",
                commit_sha="test-commit",
                root=root,
            )

            self.assertEqual("2602", manifest["airac"])
            self.assertEqual(2, manifest["schema_version"])
            self.assertEqual("2602", manifest["source_airac"])
            self.assertFalse(manifest["compatibility_fallback"])
            self.assertEqual("routes-2602.tsv", manifest["asset_name"])
            self.assertEqual(2, manifest["route_count"])

    def test_build_routes_manifest_marks_previous_cycle_compatibility_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text(
                "airac 2606\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD DCT NANDO DCT EGLL\t2605\tLainoaSoftware\n"
                "EGLL\tLEMD\tEGLL DCT SAM DCT LEMD\t2604\tLainoaSoftware\n",
                encoding="utf-8",
            )

            manifest = MODULE.build_routes_manifest(
                release_tag="daily-2026-06-11",
                asset_name="routes-2606.tsv",
                download_url="https://github.com/example/releases/download/daily-2026-06-11/routes-2606.tsv",
                published_at="2026-06-11T10:00:00Z",
                commit_sha="test-commit",
                root=root,
            )

            self.assertEqual("2606", manifest["airac"])
            self.assertEqual("2605", manifest["source_airac"])
            self.assertTrue(manifest["compatibility_fallback"])

    def test_parse_routes_file_rejects_creation_airac_newer_than_declared_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text(
                "airac 2605\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD DCT NANDO DCT EGLL\t2606\tLainoaSoftware\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "CREATION_AIRAC 2606 must not be newer than declared AIRAC 2605",
            ):
                MODULE.parse_routes_file(root)

    def test_parse_routes_file_rejects_invalid_creation_airac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text(
                "airac 2606\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD DCT NANDO DCT EGLL\tinvalid\tLainoaSoftware\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid CREATION_AIRAC 'invalid'"):
                MODULE.parse_routes_file(root)

    def test_parse_routes_file_rejects_invalid_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text("cycle 2602\nLEMD\tEGLL\tLEMD NANDO EGLL\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "first line must be 'airac <cycle>'"):
                MODULE.parse_routes_file(root)

    def test_parse_routes_file_rejects_invalid_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text("airac 2602\nORIGIN\tDEST\tROUTE\nLEMD\tEGLL\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "expected at least 3 tab-separated columns"):
                MODULE.parse_routes_file(root)

    def test_parse_routes_file_skips_empty_route_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            routes_path = root / "ROUTES" / "routes.tsv"
            routes_path.parent.mkdir(parents=True, exist_ok=True)
            routes_path.write_text(
                "airac 2602\n"
                "ORIGIN\tDEST\tROUTE\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\n"
                "OEJN\tHECA\t\n",
                encoding="utf-8",
            )

            parsed = MODULE.parse_routes_file(root)

            self.assertEqual("2602", parsed["airac"])
            self.assertEqual(1, parsed["route_count"])

    def test_build_release_manifest_includes_routes_asset(self) -> None:
        routes_manifest = {
            "schema_version": 2,
            "repo": "lainoa-software/voiceatc-simulator-community",
            "release_tag": "daily-2026-03-15",
            "commit_sha": "test-commit",
            "airac": "2602",
            "source_airac": "2601",
            "compatibility_fallback": True,
            "asset_name": "routes-2602.tsv",
            "download_url": "https://github.com/example/releases/download/daily-2026-03-15/routes-2602.tsv",
            "sha256": "abc",
            "size_bytes": 123,
            "route_count": 456,
            "published_at": "2026-03-15T01:15:00Z",
        }

        manifest = MODULE.build_release_manifest(routes_manifest, "2026-03-15T01:15:00Z")

        self.assertEqual("daily-2026-03-15", manifest["release_tag"])
        self.assertEqual(1, manifest["schema_version"])
        self.assertEqual("Daily Community Release - Sunday 2026-03-15", manifest["release_title"])
        self.assertEqual("routes-2602.tsv", manifest["assets"]["routes_tsv"]["asset_name"])
        self.assertEqual("2601", manifest["assets"]["routes_tsv"]["source_airac"])
        self.assertTrue(manifest["assets"]["routes_tsv"]["compatibility_fallback"])

    def test_validate_routes_default_file_passes_with_valid_2503_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            default_path = root / "ROUTES" / "routes_default.tsv"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text(
                "airac 2503\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "RKSS\tRKPC\tRKSS BULTI Y711 DOTOL RKPC\t2503\tLainoaSoftware\n",
                encoding="utf-8",
            )

            result = MODULE.validate_routes_default_file(root)

            self.assertEqual("2503", result["airac"])
            self.assertEqual(1, result["route_count"])

    def test_validate_routes_default_file_rejects_wrong_airac(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            default_path = root / "ROUTES" / "routes_default.tsv"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text(
                "airac 2603\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\t2603\tTester\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "expected AIRAC 2503 but found 2603"):
                MODULE.validate_routes_default_file(root)

    def test_validate_routes_default_file_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            with self.assertRaisesRegex(ValueError, "routes_default.tsv not found"):
                MODULE.validate_routes_default_file(root)

    def test_default_manifest_is_deterministic_and_validates_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            default_path = root / "ROUTES" / "routes_default.tsv"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text(
                "airac 2503\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "RKSI\tRJTT\tRKSI EGOBA Y697 LANAT RJTT\t2503\tTester\n",
                encoding="utf-8",
            )

            manifest_path = MODULE.write_default_routes_manifest(root)
            first_bytes = manifest_path.read_bytes()
            MODULE.write_default_routes_manifest(root)

            self.assertEqual(first_bytes, manifest_path.read_bytes())
            manifest = MODULE.validate_default_routes_manifest(root)
            self.assertEqual("2503", manifest["airac"])
            self.assertEqual(1, manifest["route_count"])
            self.assertEqual(len(default_path.read_bytes()), manifest["size_bytes"])

    def test_default_manifest_validation_rejects_stale_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            default_path = root / "ROUTES" / "routes_default.tsv"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text(
                "airac 2503\n"
                "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR\n"
                "RKSI\tRJTT\tRKSI EGOBA Y697 LANAT RJTT\t2503\tTester\n",
                encoding="utf-8",
            )
            manifest_path = MODULE.write_default_routes_manifest(root)
            stale = json.loads(manifest_path.read_text(encoding="utf-8"))
            stale["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(stale), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "stale default manifest fields: sha256"):
                MODULE.validate_default_routes_manifest(root)

    def test_build_release_manifest_accepts_suffixed_release_tag(self) -> None:
        routes_manifest = {
            "schema_version": 1,
            "repo": "lainoa-software/voiceatc-simulator-community",
            "release_tag": "daily-2026-03-15-b",
            "commit_sha": "test-commit",
            "airac": "2602",
            "asset_name": "routes-2602.tsv",
            "download_url": "https://github.com/example/releases/download/daily-2026-03-15-b/routes-2602.tsv",
            "sha256": "abc",
            "size_bytes": 123,
            "route_count": 456,
            "published_at": "2026-03-15T01:15:00Z",
        }

        manifest = MODULE.build_release_manifest(routes_manifest, "2026-03-15T01:15:00Z")

        self.assertEqual("Daily Community Release - Sunday 2026-03-15 b", manifest["release_title"])


if __name__ == "__main__":
    unittest.main()
