import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "visual_sight_references_manifest.py"
SPEC = importlib.util.spec_from_file_location("visual_sight_references_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def visual_payload(airport: str = "KAAA") -> dict[str, object]:
    return {
        "schema_version": 1,
        "airport": airport,
        "procedures": [
            {
                "id": "TEST_VISUAL_01",
                "variants": [
                    {
                        "id": "TEST_01",
                        "runway": "01",
                        "legs": [
                            {"id": "FIRST", "name": "First", "latitude": 40.0, "longitude": -74.0},
                            {"id": "SECOND", "name": "Second", "latitude": 40.1, "longitude": -73.9},
                        ],
                    }
                ],
            }
        ],
    }


def source_payload() -> dict[str, object]:
    return {
        "authority": "Test authority",
        "chart_title": "Test Visual Runway 01",
        "url": "https://example.invalid/test-visual-01",
        "effective_date": "2026-08-06",
        "checked_date": "2026-09-02",
    }


def sight_payload(airport: str = "KAAA") -> dict[str, object]:
    return {
        "schema_version": 1,
        "airport": airport,
        "variants": [
            {
                "procedure_id": "TEST_VISUAL_01",
                "variant_id": "TEST_01",
                "default_reference_id": "FIRST_POINT",
                "references": [
                    {
                        "id": "FIRST_POINT",
                        "name": "the first landmark",
                        "aliases": ["first landmark"],
                        "geometry": {"kind": "point", "leg_id": "FIRST"},
                        "source": source_payload(),
                    },
                    {
                        "id": "VISIBLE_ROUTE",
                        "name": "the visible route",
                        "aliases": [],
                        "geometry": {"kind": "route", "leg_ids": ["FIRST", "SECOND"]},
                        "source": source_payload(),
                    },
                    {
                        "id": "AIRPORT",
                        "name": "the airport",
                        "aliases": ["Test airport"],
                        "geometry": {"kind": "airport"},
                        "source": source_payload(),
                    },
                    {
                        "id": "RUNWAY",
                        "name": "runway one",
                        "aliases": ["runway 01"],
                        "geometry": {"kind": "runway"},
                        "source": source_payload(),
                    },
                ],
            }
        ],
    }


class VisualSightReferencesManifestTests(unittest.TestCase):
    def _write(self, root: Path, airport: str = "KAAA") -> Path:
        folder = root / "K" / "KZAA" / "AAA_TMA" / airport
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "visual_procedures.json").write_text(
            json.dumps(visual_payload(airport)), encoding="utf-8"
        )
        path = folder / "visual_sight_references.json"
        path.write_text(json.dumps(sight_payload(airport)), encoding="utf-8")
        return path

    def test_valid_file_hashes_canonical_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write(root)
            path.write_bytes((json.dumps(sight_payload(), indent=2) + "\r\n").encode("utf-8"))
            result = MODULE.validate_sight_reference_file(path, root)
            canonical = path.read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), result["sha256"])
            self.assertEqual(len(canonical), result["size_bytes"])

    def test_rejects_unknown_keys_and_invalid_geometry_union(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write(root)
            payload = sight_payload()
            payload["unexpected"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                MODULE.validate_sight_reference_file(path, root)

            payload = sight_payload()
            geometry = payload["variants"][0]["references"][0]["geometry"]
            geometry["latitude"] = 40.0
            geometry["longitude"] = -74.0
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one point representation"):
                MODULE.validate_sight_reference_file(path, root)

    def test_rejects_cross_file_ids_and_route_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write(root)
            payload = sight_payload()
            payload["variants"][0]["variant_id"] = "MISSING"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "matching visual procedure variant"):
                MODULE.validate_sight_reference_file(path, root)

            payload = sight_payload()
            payload["variants"][0]["references"][1]["geometry"]["leg_ids"] = ["SECOND", "FIRST"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source order"):
                MODULE.validate_sight_reference_file(path, root)

    def test_rejects_duplicate_spoken_phrases_and_bad_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write(root)
            payload = sight_payload()
            payload["variants"][0]["references"][1]["aliases"] = ["FIRST LANDMARK"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "spoken name or alias"):
                MODULE.validate_sight_reference_file(path, root)

            payload = sight_payload()
            payload["variants"][0]["references"][0]["source"]["url"] = "http://example.invalid"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                MODULE.validate_sight_reference_file(path, root)

    def test_manifest_is_deterministic_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root, "KBBB")
            self._write(root, "KAAA")
            first = MODULE.build_manifest(root, published_at="2026-09-02T00:00:00Z")
            second = MODULE.build_manifest(root, published_at="2026-09-02T00:00:00Z")
            self.assertEqual(first, second)
            self.assertEqual(["KAAA", "KBBB"], list(first["airports"]))
            manifest_path = root / ".voiceatc" / "visual_sight_references_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(first), encoding="utf-8")
            self.assertEqual(2, MODULE.validate_existing_manifest(root))
            first["airports"]["KAAA"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(first), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest drift"):
                MODULE.validate_existing_manifest(root)

    def test_rejects_unsafe_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root)
            manifest = MODULE.build_manifest(root, published_at="2026-09-02T00:00:00Z")
            manifest["airports"]["KAAA"]["repo_path"] = "../visual_sight_references.json"
            manifest_path = root / ".voiceatc" / "visual_sight_references_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest drift|canonical"):
                MODULE.validate_existing_manifest(root)

    def test_repository_workflows_register_sidecar_gate(self) -> None:
        validation = (ROOT / ".github" / "workflows" / "validate-content-hierarchy.yml").read_text(
            encoding="utf-8"
        )
        formatting = (ROOT / ".github" / "workflows" / "format-all-json.yml").read_text(
            encoding="utf-8"
        )
        release = (ROOT / ".github" / "workflows" / "daily-release.yml").read_text(
            encoding="utf-8"
        )
        for text in (validation, formatting, release):
            self.assertIn("visual_sight_references_manifest.py", text)
        self.assertIn("visual_sight_references_manifest.json", release)


if __name__ == "__main__":
    unittest.main()
