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
                "LEMD\tEGLL\tLEMD NANDO UN10 SAM EGLL\n"
                "EGLL\tLEMD\tEGLL SAM UL9 NANDO LEMD\n",
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
            self.assertEqual("routes-2602.tsv", manifest["asset_name"])
            self.assertEqual(2, manifest["route_count"])

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
            "schema_version": 1,
            "repo": "lainoa-software/voiceatc-simulator-community",
            "release_tag": "daily-2026-03-15",
            "commit_sha": "test-commit",
            "airac": "2602",
            "asset_name": "routes-2602.tsv",
            "download_url": "https://github.com/example/releases/download/daily-2026-03-15/routes-2602.tsv",
            "sha256": "abc",
            "size_bytes": 123,
            "route_count": 456,
            "published_at": "2026-03-15T01:15:00Z",
        }

        manifest = MODULE.build_release_manifest(routes_manifest, "2026-03-15T01:15:00Z")

        self.assertEqual("daily-2026-03-15", manifest["release_tag"])
        self.assertEqual("Daily Community Cache - Sunday 2026-03-15", manifest["release_title"])
        self.assertEqual("routes-2602.tsv", manifest["assets"]["routes_tsv"]["asset_name"])

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

        self.assertEqual("Daily Community Cache - Sunday 2026-03-15 b", manifest["release_title"])


if __name__ == "__main__":
    unittest.main()
