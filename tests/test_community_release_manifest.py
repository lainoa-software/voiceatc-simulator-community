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
    routes_path = root / "ROUTES" / "routes.tsv"
    routes_path.parent.mkdir(parents=True, exist_ok=True)
    routes_path.write_text(
        "\n".join(
            [
                "airac 2602",
                "ORIGIN\tDEST\tFULL_ROUTE",
                "LEMD\tLEBL\tLEMD TEST LEBL",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

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


class CommunityReleaseManifestTests(unittest.TestCase):
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
            self.assertEqual("mva-2602.zip", bundle["assets"]["mva_zip"]["asset_name"])
            self.assertEqual("runway-configs-2602.zip", bundle["assets"]["runway_configs_zip"]["asset_name"])
            self.assertEqual("release-manifest.json", bundle["assets"]["release_manifest"]["asset_name"])

            release_manifest = bundle["manifests"]["release"]
            self.assertEqual(2, release_manifest["schema_version"])
            self.assertEqual("daily-2026-03-18", release_manifest["release_tag"])
            self.assertEqual("Daily Community Cache - Wednesday 2026-03-18", release_manifest["release_title"])
            self.assertIn("mva_zip", release_manifest["assets"])
            self.assertIn("runway_configs_zip", release_manifest["assets"])

            mva_manifest = bundle["manifests"]["mva"]
            self.assertEqual(2, mva_manifest["schema_version"])
            self.assertEqual("mva-2602.zip", mva_manifest["asset_name"])
            self.assertEqual(2, mva_manifest["airport_count"])

            runway_manifest = bundle["manifests"]["runway_configs"]
            self.assertEqual(2, runway_manifest["schema_version"])
            self.assertEqual("runway-configs-2602.zip", runway_manifest["asset_name"])
            self.assertEqual(2, runway_manifest["airport_count"])

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

    def test_build_release_bundle_accepts_suffixed_manual_release_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "repo"
            build_fixture_repo(root)

            bundle = MODULE.build_release_bundle(
                output_dir=root / "build" / "manual",
                release_tag="daily-2026-03-18-b",
                release_title="Daily Community Cache - Wednesday 2026-03-18 b",
                published_at="2026-03-18T12:15:00Z",
                commit_sha="test-commit",
                download_repo="lainoa-software/voiceatc-simulator-community",
                root=root,
            )

            release_manifest = bundle["manifests"]["release"]
            self.assertEqual("daily-2026-03-18-b", release_manifest["release_tag"])
            self.assertEqual("Daily Community Cache - Wednesday 2026-03-18 b", release_manifest["release_title"])


if __name__ == "__main__":
    unittest.main()
